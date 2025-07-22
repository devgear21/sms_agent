"""
Logger Node
Handles comprehensive logging for SMS agent monitoring and debugging
"""

import os
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from langsmith import traceable
import structlog
from enum import Enum

# Configure structured logging
logger = structlog.get_logger()

class LogLevel(Enum):
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"

class SMSAgentLogger:
    def __init__(self):
        """Initialize comprehensive logging for SMS agent"""
        self.log_level = os.getenv('LOG_LEVEL', 'INFO').upper()
        logger.info("SMS Agent logger initialized", log_level=self.log_level)

    @traceable(
        name="log_conversation_event",
        tags=["logging", "conversation", "tracking"],
        metadata={"component": "conversation_logger"}
    )
    def log_conversation_event(self, event_type: str, session_id: str, 
                              phone_number: str, data: Dict[str, Any],
                              level: LogLevel = LogLevel.INFO) -> Dict[str, Any]:
        """
        Log conversation events with full context
        
        Args:
            event_type: Type of event (phone_validation, sms_sent, booking_created, etc.)
            session_id: Session identifier
            phone_number: User's phone number (masked for privacy)
            data: Event-specific data
            level: Log level
        
        Returns:
            Dict with logging results
        """
        
        # Mask phone number for privacy (show last 4 digits only)
        masked_phone = self._mask_phone_number(phone_number)
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": event_type,
            "session_id": session_id,
            "phone_number": masked_phone,
            "level": level.value,
            "data": data
        }
        
        # Log based on level
        if level == LogLevel.DEBUG:
            logger.debug("Conversation event", **log_entry)
        elif level == LogLevel.INFO:
            logger.info("Conversation event", **log_entry)
        elif level == LogLevel.WARNING:
            logger.warning("Conversation event", **log_entry)
        elif level == LogLevel.ERROR:
            logger.error("Conversation event", **log_entry)
        elif level == LogLevel.CRITICAL:
            logger.critical("Conversation event", **log_entry)
        
        return {
            "logged": True,
            "timestamp": log_entry["timestamp"],
            "sessionId": session_id,
            "eventType": event_type
        }

    @traceable(
        name="log_api_call",
        tags=["logging", "api", "monitoring"],
        metadata={"component": "api_logger"}
    )
    def log_api_call(self, api_name: str, session_id: str, method: str,
                    endpoint: str, status_code: Optional[int] = None,
                    response_time_ms: Optional[float] = None,
                    error: Optional[str] = None) -> Dict[str, Any]:
        """
        Log API calls for monitoring and debugging
        
        Args:
            api_name: Name of the API (twilio, calendly, groq)
            session_id: Session identifier
            method: HTTP method
            endpoint: API endpoint
            status_code: HTTP status code
            response_time_ms: Response time in milliseconds
            error: Error message if any
        
        Returns:
            Dict with logging results
        """
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "api_call",
            "api_name": api_name,
            "session_id": session_id,
            "method": method,
            "endpoint": endpoint,
            "status_code": status_code,
            "response_time_ms": response_time_ms,
            "success": status_code is not None and 200 <= status_code < 300,
            "error": error
        }
        
        if error or (status_code and status_code >= 400):
            logger.error("API call failed", **log_entry)
        else:
            logger.info("API call completed", **log_entry)
        
        return {
            "logged": True,
            "timestamp": log_entry["timestamp"],
            "sessionId": session_id,
            "apiName": api_name,
            "success": log_entry["success"]
        }

    @traceable(
        name="log_sms_failure",
        tags=["logging", "sms", "failure"],
        metadata={"component": "sms_failure_logger"}
    )
    def log_sms_failure(self, failure_type: str, session_id: str,
                       phone_number: str, error_details: Dict[str, Any],
                       retry_count: int = 0) -> Dict[str, Any]:
        """
        Log SMS delivery failures for monitoring and alerts
        
        Args:
            failure_type: Type of SMS failure (delivery, rate_limit, invalid_number)
            session_id: Session identifier
            phone_number: User's phone number
            error_details: Detailed error information
            retry_count: Number of retry attempts
        
        Returns:
            Dict with logging results
        """
        
        masked_phone = self._mask_phone_number(phone_number)
        
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "sms_failure",
            "failure_type": failure_type,
            "session_id": session_id,
            "phone_number": masked_phone,
            "retry_count": retry_count,
            "error_details": error_details,
            "severity": "high" if retry_count >= 3 else "medium"
        }
        
        logger.error("SMS delivery failure", **log_entry)
        
        # Could trigger alerts here for high-severity failures
        if retry_count >= 3:
            self._trigger_sms_failure_alert(log_entry)
        
        return {
            "logged": True,
            "timestamp": log_entry["timestamp"],
            "sessionId": session_id,
            "failureType": failure_type,
            "severity": log_entry["severity"]
        }

    @traceable(
        name="log_booking_metrics",
        tags=["logging", "metrics", "analytics"],
        metadata={"component": "metrics_logger"}
    )
    def log_booking_metrics(self, session_id: str, phone_number: str,
                           conversation_start: str, conversation_end: str,
                           outcome: str, steps: List[str],
                           error_count: int = 0) -> Dict[str, Any]:
        """
        Log booking session metrics for analytics
        
        Args:
            session_id: Session identifier
            phone_number: User's phone number
            conversation_start: Start timestamp
            conversation_end: End timestamp
            outcome: Final outcome (booked, cancelled, failed, abandoned)
            steps: List of conversation steps taken
            error_count: Number of errors encountered
        
        Returns:
            Dict with logging results
        """
        
        # Calculate conversation duration
        start_dt = datetime.fromisoformat(conversation_start.replace('Z', '+00:00'))
        end_dt = datetime.fromisoformat(conversation_end.replace('Z', '+00:00'))
        duration_seconds = (end_dt - start_dt).total_seconds()
        
        masked_phone = self._mask_phone_number(phone_number)
        
        metrics_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "booking_metrics",
            "session_id": session_id,
            "phone_number": masked_phone,
            "conversation_start": conversation_start,
            "conversation_end": conversation_end,
            "duration_seconds": duration_seconds,
            "outcome": outcome,
            "steps_count": len(steps),
            "steps": steps,
            "error_count": error_count,
            "success": outcome == "booked"
        }
        
        logger.info("Booking session completed", **metrics_entry)
        
        return {
            "logged": True,
            "timestamp": metrics_entry["timestamp"],
            "sessionId": session_id,
            "outcome": outcome,
            "durationSeconds": duration_seconds,
            "success": metrics_entry["success"]
        }

    def _mask_phone_number(self, phone_number: str) -> str:
        """Mask phone number for privacy (show last 4 digits only)"""
        if len(phone_number) >= 4:
            return f"***-***-{phone_number[-4:]}"
        return "***-***-****"

    def _trigger_sms_failure_alert(self, log_entry: Dict[str, Any]) -> None:
        """Trigger alert for critical SMS failures"""
        # In production, this would send alerts to monitoring systems
        # For now, just log a critical alert
        logger.critical("ALERT: High-severity SMS failure", 
                       alert_type="sms_failure",
                       **log_entry)

    @traceable(
        name="log_system_health",
        tags=["logging", "health", "monitoring"],
        metadata={"component": "health_logger"}
    )
    def log_system_health(self, component: str, status: str, 
                         metrics: Dict[str, Any]) -> Dict[str, Any]:
        """
        Log system health metrics
        
        Args:
            component: System component name
            status: Health status (healthy, degraded, down)
            metrics: Component-specific metrics
        
        Returns:
            Dict with logging results
        """
        
        health_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "event_type": "system_health",
            "component": component,
            "status": status,
            "metrics": metrics
        }
        
        if status == "down":
            logger.critical("System component down", **health_entry)
        elif status == "degraded":
            logger.warning("System component degraded", **health_entry)
        else:
            logger.info("System component healthy", **health_entry)
        
        return {
            "logged": True,
            "timestamp": health_entry["timestamp"],
            "component": component,
            "status": status
        }

# Global logger instance
sms_logger = SMSAgentLogger()

@traceable(
    name="log_sms_failure",
    tags=["logging", "failure"],
    metadata={"component": "failure_log"}
)
def log_sms_failure(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for logging SMS failures
    
    Args:
        inputs: Dict containing error, sessionId, phoneNumber
    
    Returns:
        Dict with logging results
    """
    
    error = inputs.get('error', '')
    session_id = inputs.get('sessionId', '')
    phone_number = inputs.get('phoneNumber', '')
    retry_count = inputs.get('retryCount', 0)
    
    # Determine failure type from error message
    error_lower = error.lower()
    if 'rate limit' in error_lower or 'too many' in error_lower:
        failure_type = "rate_limit"
    elif 'invalid' in error_lower and 'number' in error_lower:
        failure_type = "invalid_number"
    elif 'delivery' in error_lower or 'failed' in error_lower:
        failure_type = "delivery_failure"
    else:
        failure_type = "unknown"
    
    error_details = {
        "error_message": error,
        "timestamp": datetime.now(timezone.utc).isoformat()
    }
    
    return sms_logger.log_sms_failure(
        failure_type=failure_type,
        session_id=session_id,
        phone_number=phone_number,
        error_details=error_details,
        retry_count=retry_count
    )

@traceable(
    name="log_conversation_step",
    tags=["logging", "conversation"],
    metadata={"component": "conversation_log"}
)
def log_conversation_step(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Log individual conversation steps
    
    Args:
        inputs: Dict containing step details
    
    Returns:
        Dict with logging results
    """
    
    step_name = inputs.get('stepName', '')
    session_id = inputs.get('sessionId', '')
    phone_number = inputs.get('phoneNumber', '')
    step_data = inputs.get('stepData', {})
    success = inputs.get('success', True)
    
    level = LogLevel.INFO if success else LogLevel.ERROR
    
    return sms_logger.log_conversation_event(
        event_type=f"conversation_step_{step_name}",
        session_id=session_id,
        phone_number=phone_number,
        data=step_data,
        level=level
    )

# Test function
if __name__ == "__main__":
    # Test logging functionality
    test_session_id = "test-session-logger"
    test_phone = "+1234567890"
    
    print("Testing SMS agent logging...")
    
    # Test conversation event logging
    result1 = sms_logger.log_conversation_event(
        event_type="phone_validation",
        session_id=test_session_id,
        phone_number=test_phone,
        data={"validation_result": "success", "formatted_number": "+1234567890"}
    )
    print(f"Conversation event log: {result1}")
    
    # Test API call logging
    result2 = sms_logger.log_api_call(
        api_name="twilio",
        session_id=test_session_id,
        method="POST",
        endpoint="/messages",
        status_code=201,
        response_time_ms=250.5
    )
    print(f"API call log: {result2}")
    
    # Test SMS failure logging
    result3 = log_sms_failure({
        "error": "Message delivery failed",
        "sessionId": test_session_id,
        "phoneNumber": test_phone,
        "retryCount": 1
    })
    print(f"SMS failure log: {result3}")
    
    # Test booking metrics
    result4 = sms_logger.log_booking_metrics(
        session_id=test_session_id,
        phone_number=test_phone,
        conversation_start="2025-01-22T10:00:00Z",
        conversation_end="2025-01-22T10:05:30Z",
        outcome="booked",
        steps=["phone_validation", "welcome_sms", "groq_processing", "calendly_booking", "confirmation"],
        error_count=0
    )
    print(f"Booking metrics log: {result4}")
