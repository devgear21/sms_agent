"""
LangSmith Tracing Configuration
Sets up comprehensive monitoring and tracing for the SMS agent
"""

import os
from typing import Dict, Any, Optional, List
from langsmith import Client, RunTree
from langsmith.schemas import Run, RunCreate
from datetime import datetime, timezone
import json
import structlog

# Configure structured logging
logger = structlog.get_logger()

class LangSmithMonitor:
    def __init__(self):
        """Initialize LangSmith monitoring and tracing"""
        self.api_key = os.getenv('LANGSMITH_API_KEY')
        self.project_name = os.getenv('LANGSMITH_PROJECT_NAME', 'sms-appointment-booking')
        self.endpoint = os.getenv('LANGSMITH_ENDPOINT', 'https://api.smith.langchain.com')
        
        if not self.api_key:
            raise ValueError("LANGSMITH_API_KEY environment variable is required")
        
        # Initialize LangSmith client
        self.client = Client(
            api_url=self.endpoint,
            api_key=self.api_key
        )
        
        # Ensure project exists
        try:
            self.client.create_project(
                project_name=self.project_name,
                description="SMS appointment booking agent with Calendly integration"
            )
        except Exception:
            # Project likely already exists
            pass
        
        logger.info("LangSmith monitoring initialized", 
                   project_name=self.project_name,
                   endpoint=self.endpoint)

    def create_session_trace(self, session_id: str, phone_number: str, 
                           initial_message: str) -> RunTree:
        """
        Create a root trace for an entire conversation session
        
        Args:
            session_id: Unique session identifier
            phone_number: User's phone number (masked)
            initial_message: Initial SMS message
        
        Returns:
            RunTree object for the session
        """
        
        session_trace = RunTree(
            name="sms_conversation_session",
            inputs={
                "session_id": session_id,
                "phone_number": self._mask_phone_number(phone_number),
                "initial_message": initial_message,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            project_name=self.project_name,
            tags=["sms", "conversation", "session"],
            metadata={
                "session_id": session_id,
                "component": "conversation_session",
                "phone_number_hash": self._hash_phone_number(phone_number)
            }
        )
        
        logger.info("Created session trace", 
                   session_id=session_id,
                   trace_id=session_trace.id)
        
        return session_trace

    def trace_node_execution(self, node_name: str, session_id: str,
                           inputs: Dict[str, Any], outputs: Dict[str, Any],
                           duration_ms: float, success: bool = True,
                           error: Optional[str] = None,
                           parent_trace: Optional[RunTree] = None) -> RunTree:
        """
        Trace execution of a graph node
        
        Args:
            node_name: Name of the executed node
            session_id: Session identifier
            inputs: Node inputs
            outputs: Node outputs
            duration_ms: Execution duration in milliseconds
            success: Whether execution was successful
            error: Error message if any
            parent_trace: Parent trace to attach to
        
        Returns:
            RunTree object for the node execution
        """
        
        # Clean sensitive data from inputs/outputs
        clean_inputs = self._clean_sensitive_data(inputs)
        clean_outputs = self._clean_sensitive_data(outputs)
        
        node_trace = RunTree(
            name=f"node_{node_name}",
            inputs=clean_inputs,
            outputs=clean_outputs,
            project_name=self.project_name,
            tags=["node", node_name, "execution"],
            metadata={
                "session_id": session_id,
                "node_name": node_name,
                "duration_ms": duration_ms,
                "success": success,
                "error": error,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            parent=parent_trace
        )
        
        # Set run type based on node
        if "llm" in node_name.lower() or "groq" in node_name.lower():
            node_trace.run_type = "llm"
        elif "api" in node_name.lower() or "calendly" in node_name.lower() or "twilio" in node_name.lower():
            node_trace.run_type = "tool"
        else:
            node_trace.run_type = "chain"
        
        if not success and error:
            node_trace.error = error
        
        logger.info("Traced node execution", 
                   node_name=node_name,
                   session_id=session_id,
                   success=success,
                   duration_ms=duration_ms)
        
        return node_trace

    def trace_api_call(self, api_name: str, endpoint: str, method: str,
                      session_id: str, request_data: Dict[str, Any],
                      response_data: Dict[str, Any], status_code: int,
                      duration_ms: float, parent_trace: Optional[RunTree] = None) -> RunTree:
        """
        Trace external API calls
        
        Args:
            api_name: Name of the API (twilio, calendly, groq)
            endpoint: API endpoint
            method: HTTP method
            session_id: Session identifier
            request_data: Request payload
            response_data: Response data
            status_code: HTTP status code
            duration_ms: Request duration
            parent_trace: Parent trace to attach to
        
        Returns:
            RunTree object for the API call
        """
        
        # Clean sensitive data
        clean_request = self._clean_api_data(request_data, api_name)
        clean_response = self._clean_api_data(response_data, api_name)
        
        api_trace = RunTree(
            name=f"api_{api_name}_{method.lower()}",
            inputs={
                "endpoint": endpoint,
                "method": method,
                "request_data": clean_request
            },
            outputs={
                "status_code": status_code,
                "response_data": clean_response
            },
            project_name=self.project_name,
            tags=["api", api_name, method.lower()],
            metadata={
                "session_id": session_id,
                "api_name": api_name,
                "endpoint": endpoint,
                "method": method,
                "status_code": status_code,
                "duration_ms": duration_ms,
                "success": 200 <= status_code < 300,
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            parent=parent_trace,
            run_type="tool"
        )
        
        if status_code >= 400:
            api_trace.error = f"API call failed with status {status_code}"
        
        logger.info("Traced API call", 
                   api_name=api_name,
                   endpoint=endpoint,
                   status_code=status_code,
                   duration_ms=duration_ms)
        
        return api_trace

    def trace_llm_call(self, model_name: str, session_id: str,
                      messages: List[Dict[str, str]], response: str,
                      duration_ms: float, token_usage: Optional[Dict[str, int]] = None,
                      parent_trace: Optional[RunTree] = None) -> RunTree:
        """
        Trace LLM calls with detailed information
        
        Args:
            model_name: Name of the LLM model
            session_id: Session identifier
            messages: List of messages sent to LLM
            response: LLM response
            duration_ms: Call duration
            token_usage: Token usage statistics
            parent_trace: Parent trace to attach to
        
        Returns:
            RunTree object for the LLM call
        """
        
        llm_trace = RunTree(
            name=f"llm_{model_name}",
            inputs={
                "messages": messages,
                "model": model_name
            },
            outputs={
                "response": response,
                "token_usage": token_usage or {}
            },
            project_name=self.project_name,
            tags=["llm", model_name, "completion"],
            metadata={
                "session_id": session_id,
                "model_name": model_name,
                "duration_ms": duration_ms,
                "message_count": len(messages),
                "response_length": len(response),
                "timestamp": datetime.now(timezone.utc).isoformat()
            },
            parent=parent_trace,
            run_type="llm"
        )
        
        logger.info("Traced LLM call", 
                   model_name=model_name,
                   session_id=session_id,
                   duration_ms=duration_ms,
                   token_usage=token_usage)
        
        return llm_trace

    def finalize_session_trace(self, session_trace: RunTree, 
                             final_outcome: str, total_duration_ms: float,
                             error_count: int = 0, 
                             final_error: Optional[str] = None) -> None:
        """
        Finalize and submit the session trace
        
        Args:
            session_trace: The session trace to finalize
            final_outcome: Final outcome (booked, failed, abandoned)
            total_duration_ms: Total session duration
            error_count: Number of errors encountered
            final_error: Final error if session failed
        """
        
        session_trace.outputs = {
            "final_outcome": final_outcome,
            "total_duration_ms": total_duration_ms,
            "error_count": error_count,
            "success": final_outcome == "booked",
            "completion_timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if final_error:
            session_trace.error = final_error
        
        # Submit the trace
        session_trace.post()
        
        logger.info("Finalized session trace", 
                   session_id=session_trace.metadata.get('session_id'),
                   final_outcome=final_outcome,
                   total_duration_ms=total_duration_ms,
                   error_count=error_count)

    def _mask_phone_number(self, phone_number: str) -> str:
        """Mask phone number for privacy"""
        if len(phone_number) >= 4:
            return f"***-***-{phone_number[-4:]}"
        return "***-***-****"

    def _hash_phone_number(self, phone_number: str) -> str:
        """Create a hash of phone number for grouping without exposing PII"""
        import hashlib
        return hashlib.sha256(phone_number.encode()).hexdigest()[:16]

    def _clean_sensitive_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Remove or mask sensitive data from trace inputs/outputs"""
        if not isinstance(data, dict):
            return data
        
        cleaned = {}
        sensitive_keys = ['phone_number', 'phoneNumber', 'auth_token', 'api_key', 'password']
        
        for key, value in data.items():
            if any(sensitive_key in key.lower() for sensitive_key in sensitive_keys):
                if 'phone' in key.lower():
                    cleaned[key] = self._mask_phone_number(str(value))
                else:
                    cleaned[key] = "***REDACTED***"
            else:
                cleaned[key] = value
        
        return cleaned

    def _clean_api_data(self, data: Dict[str, Any], api_name: str) -> Dict[str, Any]:
        """Clean API-specific sensitive data"""
        if not isinstance(data, dict):
            return data
        
        cleaned = self._clean_sensitive_data(data)
        
        # API-specific cleaning
        if api_name.lower() == 'twilio':
            # Remove auth headers and account SIDs
            for key in list(cleaned.keys()):
                if 'sid' in key.lower() or 'auth' in key.lower():
                    cleaned[key] = "***REDACTED***"
        
        elif api_name.lower() == 'calendly':
            # Remove tokens and URIs that might contain sensitive info
            for key in list(cleaned.keys()):
                if 'token' in key.lower() or 'uri' in key.lower():
                    if 'event_type' not in key.lower():  # Keep event_type URIs
                        cleaned[key] = "***REDACTED***"
        
        return cleaned

    def create_dashboard_config(self) -> Dict[str, Any]:
        """
        Create LangSmith dashboard configuration for monitoring
        
        Returns:
            Dashboard configuration dict
        """
        
        dashboard_config = {
            "name": "SMS Appointment Agent Dashboard",
            "description": "Monitoring dashboard for SMS appointment booking agent",
            "charts": [
                {
                    "name": "Conversation Success Rate",
                    "type": "metric",
                    "query": {
                        "project": self.project_name,
                        "filter": "name = 'sms_conversation_session'",
                        "metric": "success_rate"
                    }
                },
                {
                    "name": "Average Conversation Duration",
                    "type": "metric", 
                    "query": {
                        "project": self.project_name,
                        "filter": "name = 'sms_conversation_session'",
                        "metric": "avg_duration"
                    }
                },
                {
                    "name": "Error Rate by Node",
                    "type": "bar_chart",
                    "query": {
                        "project": self.project_name,
                        "filter": "name LIKE 'node_%'",
                        "group_by": "metadata.node_name",
                        "metric": "error_rate"
                    }
                },
                {
                    "name": "API Response Times",
                    "type": "line_chart",
                    "query": {
                        "project": self.project_name,
                        "filter": "name LIKE 'api_%'",
                        "group_by": "metadata.api_name",
                        "metric": "avg_duration"
                    }
                },
                {
                    "name": "Daily Booking Volume",
                    "type": "line_chart",
                    "query": {
                        "project": self.project_name,
                        "filter": "name = 'sms_conversation_session' AND outputs.final_outcome = 'booked'",
                        "group_by": "date",
                        "metric": "count"
                    }
                }
            ],
            "alerts": [
                {
                    "name": "High Error Rate Alert",
                    "condition": "error_rate > 0.1",
                    "query": {
                        "project": self.project_name,
                        "time_window": "1h"
                    },
                    "notification_channels": ["email"]
                },
                {
                    "name": "API Latency Alert", 
                    "condition": "avg_duration > 5000",
                    "query": {
                        "project": self.project_name,
                        "filter": "name LIKE 'api_%'",
                        "time_window": "15m"
                    },
                    "notification_channels": ["slack"]
                }
            ]
        }
        
        return dashboard_config

# Global monitor instance
langsmith_monitor = LangSmithMonitor()

# Test function
if __name__ == "__main__":
    # Test LangSmith tracing
    print("Testing LangSmith tracing...")
    
    # Create a test session trace
    session_trace = langsmith_monitor.create_session_trace(
        session_id="test-session-123",
        phone_number="+1234567890",
        initial_message="I want to book an appointment tomorrow at 2pm"
    )
    
    # Trace a node execution
    node_trace = langsmith_monitor.trace_node_execution(
        node_name="phone_validator",
        session_id="test-session-123",
        inputs={"From": "+1234567890", "Body": "I want to book an appointment"},
        outputs={"phoneNumber": "+1234567890", "isValid": True},
        duration_ms=150.5,
        success=True,
        parent_trace=session_trace
    )
    
    # Trace an API call
    api_trace = langsmith_monitor.trace_api_call(
        api_name="twilio",
        endpoint="/messages",
        method="POST",
        session_id="test-session-123",
        request_data={"to": "+1234567890", "body": "Welcome message"},
        response_data={"sid": "msg123", "status": "sent"},
        status_code=201,
        duration_ms=250.0,
        parent_trace=session_trace
    )
    
    # Finalize the session
    langsmith_monitor.finalize_session_trace(
        session_trace=session_trace,
        final_outcome="booked",
        total_duration_ms=5000.0,
        error_count=0
    )
    
    print("LangSmith tracing test completed!")
    
    # Print dashboard config
    dashboard_config = langsmith_monitor.create_dashboard_config()
    print(f"\nDashboard config: {json.dumps(dashboard_config, indent=2)}")
