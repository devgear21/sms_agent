"""
SMS Appointment Booking Agent - Main Application
FastAPI application that serves as the webhook endpoint and orchestrates the LangGraph workflow
"""

import os
import time
from datetime import datetime, timezone
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, HTTPException, BackgroundTasks
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import uvicorn
import structlog
from dotenv import load_dotenv

# Import our nodes
from nodes.phone_validator import validate_phone_number
from nodes.twilio_sender import send_welcome_sms, send_confirmation_sms
from nodes.groq_processor import process_user_message
from nodes.calendly_checker import check_calendly_availability
from nodes.calendly_creator import create_calendly_event
from nodes.error_handler import send_error_sms
from nodes.fallback_handler import send_fallback_response
from nodes.logger import sms_logger

# Import LangSmith monitoring
from tracing.langsmith_monitor import langsmith_monitor

# Load environment variables
load_dotenv()

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.JSONRenderer()
    ],
    context_class=dict,
    logger_factory=structlog.stdlib.LoggerFactory(),
    wrapper_class=structlog.stdlib.BoundLogger,
    cache_logger_on_first_use=True,
)

logger = structlog.get_logger()

# FastAPI app
app = FastAPI(
    title="SMS Appointment Booking Agent",
    description="LangGraph-powered SMS agent for appointment booking with Calendly integration",
    version="1.0.0"
)

# Simple in-memory session store (in production, use Redis)
session_store: Dict[str, Dict[str, Any]] = {}

class TwilioWebhook(BaseModel):
    """Pydantic model for Twilio webhook payload"""
    MessageSid: str
    AccountSid: str
    From: str
    To: str
    Body: str
    NumMedia: Optional[str] = "0"

class ConversationOrchestrator:
    """Orchestrates the conversation flow through LangGraph nodes"""
    
    def __init__(self):
        self.logger = logger
    
    async def process_sms(self, webhook_data: TwilioWebhook) -> Dict[str, Any]:
        """
        Process incoming SMS through the LangGraph workflow
        
        Args:
            webhook_data: Twilio webhook payload
        
        Returns:
            Processing results
        """
        
        start_time = time.time()
        session_trace = None
        
        try:
            # Step 1: Validate phone number
            validation_start = time.time()
            validation_result = validate_phone_number({
                'From': webhook_data.From,
                'Body': webhook_data.Body
            })
            validation_duration = (time.time() - validation_start) * 1000
            
            if not validation_result.get('isValid'):
                # Send error SMS for invalid phone
                await self._send_error_and_log(
                    phone_number=webhook_data.From,
                    error_type="phone_validation",
                    session_id=validation_result.get('sessionId', ''),
                    context={"original_number": webhook_data.From}
                )
                return {"status": "error", "message": "Invalid phone number"}
            
            # Extract validated data
            phone_number = validation_result['phoneNumber']
            session_id = validation_result['sessionId']
            user_message = validation_result['userMessage']
            
            # Create LangSmith session trace
            session_trace = langsmith_monitor.create_session_trace(
                session_id=session_id,
                phone_number=phone_number,
                initial_message=user_message
            )
            
            # Trace phone validation
            langsmith_monitor.trace_node_execution(
                node_name="phone_validator",
                session_id=session_id,
                inputs={'From': webhook_data.From, 'Body': webhook_data.Body},
                outputs=validation_result,
                duration_ms=validation_duration,
                success=True,
                parent_trace=session_trace
            )
            
            # Initialize or update session state
            session_state = self._get_or_create_session(session_id, phone_number)
            session_state['lastMessage'] = user_message
            session_state['lastActivity'] = datetime.now(timezone.utc).isoformat()
            
            # Step 2: Send welcome SMS if new session
            if session_state['conversationState'] == 'new':
                await self._send_welcome_message(session_id, phone_number, session_trace)
                session_state['conversationState'] = 'collecting_preferences'
            
            # Step 3: Process user message with Groq
            groq_result = await self._process_with_groq(
                user_message, session_state, session_id, session_trace
            )
            
            if not groq_result.get('success'):
                await self._send_fallback_response(
                    phone_number, user_message, session_id, session_trace
                )
                return {"status": "fallback", "session_id": session_id}
            
            # Step 4: Handle conversation flow based on Groq results
            extracted_datetime = groq_result.get('extracted_datetime')
            needs_more_info = groq_result.get('needs_more_info', True)
            
            if extracted_datetime and not needs_more_info:
                # Step 5: Check Calendly availability
                availability_result = await self._check_availability(
                    extracted_datetime, session_id, session_trace
                )
                
                if availability_result.get('isAvailable'):
                    # Step 6: Create Calendly event
                    booking_result = await self._create_booking(
                        extracted_datetime, phone_number, session_id, session_trace
                    )
                    
                    if booking_result.get('success'):
                        # Step 7: Send confirmation SMS
                        await self._send_confirmation(
                            phone_number, booking_result, session_id, session_trace
                        )
                        session_state['conversationState'] = 'completed'
                        
                        # Log successful booking metrics
                        total_duration = (time.time() - start_time) * 1000
                        sms_logger.log_booking_metrics(
                            session_id=session_id,
                            phone_number=phone_number,
                            conversation_start=session_state['startTime'],
                            conversation_end=datetime.now(timezone.utc).isoformat(),
                            outcome="booked",
                            steps=session_state.get('steps', []),
                            error_count=session_state.get('errorCount', 0)
                        )
                        
                        # Finalize session trace
                        if session_trace:
                            langsmith_monitor.finalize_session_trace(
                                session_trace=session_trace,
                                final_outcome="booked",
                                total_duration_ms=total_duration,
                                error_count=session_state.get('errorCount', 0)
                            )
                        
                        return {"status": "booked", "session_id": session_id}
                    
                    else:
                        await self._send_error_and_log(
                            phone_number, "calendly_booking", session_id,
                            context=booking_result
                        )
                
                else:
                    # Send availability alternatives
                    await self._send_availability_response(
                        phone_number, availability_result, session_id, session_trace
                    )
            
            else:
                # Need more information - Groq response should guide user
                # Response already sent by Groq processing
                session_state['conversationState'] = 'collecting_preferences'
            
            return {"status": "processing", "session_id": session_id}
        
        except Exception as e:
            error_msg = f"Conversation processing error: {str(e)}"
            self.logger.error("Conversation orchestration failed", 
                            error=str(e),
                            webhook_data=webhook_data.dict())
            
            # Send error message to user
            if 'session_id' in locals():
                await self._send_error_and_log(
                    phone_number=webhook_data.From,
                    error_type="general",
                    session_id=session_id,
                    context={"error": str(e)}
                )
            
            # Finalize session trace with error
            if session_trace:
                total_duration = (time.time() - start_time) * 1000
                langsmith_monitor.finalize_session_trace(
                    session_trace=session_trace,
                    final_outcome="failed",
                    total_duration_ms=total_duration,
                    error_count=1,
                    final_error=str(e)
                )
            
            return {"status": "error", "message": error_msg}
    
    def _get_or_create_session(self, session_id: str, phone_number: str) -> Dict[str, Any]:
        """Get existing session or create new one"""
        if session_id not in session_store:
            session_store[session_id] = {
                'sessionId': session_id,
                'phoneNumber': phone_number,
                'conversationState': 'new',
                'startTime': datetime.now(timezone.utc).isoformat(),
                'steps': [],
                'errorCount': 0,
                'messages': []
            }
        return session_store[session_id]
    
    async def _send_welcome_message(self, session_id: str, phone_number: str, 
                                   session_trace: Any) -> None:
        """Send welcome SMS message"""
        start_time = time.time()
        
        welcome_result = send_welcome_sms({
            'phoneNumber': phone_number,
            'sessionId': session_id
        })
        
        duration = (time.time() - start_time) * 1000
        
        # Trace welcome SMS
        langsmith_monitor.trace_node_execution(
            node_name="send_welcome_sms",
            session_id=session_id,
            inputs={'phoneNumber': phone_number, 'sessionId': session_id},
            outputs=welcome_result,
            duration_ms=duration,
            success=welcome_result.get('messageSent', False),
            error=welcome_result.get('error'),
            parent_trace=session_trace
        )
    
    async def _process_with_groq(self, user_message: str, session_state: Dict[str, Any],
                                session_id: str, session_trace: Any) -> Dict[str, Any]:
        """Process message with Groq LLM"""
        start_time = time.time()
        
        try:
            groq_result = process_user_message({
                'userMessage': user_message,
                'conversationState': session_state['conversationState'],
                'sessionId': session_id,
                'context': {
                    'previous_messages': session_state.get('messages', [])[-3:]  # Last 3 messages
                }
            })
            
            duration = (time.time() - start_time) * 1000
            
            # Trace Groq processing
            langsmith_monitor.trace_node_execution(
                node_name="groq_processor",
                session_id=session_id,
                inputs={'userMessage': user_message, 'conversationState': session_state['conversationState']},
                outputs=groq_result,
                duration_ms=duration,
                success=groq_result.get('extracted_datetime') is not None or groq_result.get('needs_more_info'),
                parent_trace=session_trace
            )
            
            # Send Groq's response to user (if provided)
            if groq_result.get('response_message'):
                # Implementation would send SMS here
                pass
            
            # Update session
            session_state['messages'].append({
                'user': user_message,
                'assistant': groq_result.get('response_message', ''),
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            session_state['steps'].append('groq_processing')
            
            return {'success': True, **groq_result}
            
        except Exception as e:
            duration = (time.time() - start_time) * 1000
            
            # Trace error
            langsmith_monitor.trace_node_execution(
                node_name="groq_processor",
                session_id=session_id,
                inputs={'userMessage': user_message},
                outputs={},
                duration_ms=duration,
                success=False,
                error=str(e),
                parent_trace=session_trace
            )
            
            session_state['errorCount'] += 1
            return {'success': False, 'error': str(e)}
    
    async def _check_availability(self, requested_datetime: str, session_id: str,
                                 session_trace: Any) -> Dict[str, Any]:
        """Check Calendly availability"""
        start_time = time.time()
        
        availability_result = check_calendly_availability({
            'requestedDateTime': requested_datetime,
            'sessionId': session_id
        })
        
        duration = (time.time() - start_time) * 1000
        
        # Trace availability check
        langsmith_monitor.trace_node_execution(
            node_name="calendly_checker",
            session_id=session_id,
            inputs={'requestedDateTime': requested_datetime},
            outputs=availability_result,
            duration_ms=duration,
            success=availability_result.get('isAvailable') is not None,
            error=availability_result.get('error'),
            parent_trace=session_trace
        )
        
        return availability_result
    
    async def _create_booking(self, requested_datetime: str, phone_number: str,
                             session_id: str, session_trace: Any) -> Dict[str, Any]:
        """Create Calendly booking"""
        start_time = time.time()
        
        booking_result = create_calendly_event({
            'requestedDateTime': requested_datetime,
            'phoneNumber': phone_number,
            'sessionId': session_id
        })
        
        duration = (time.time() - start_time) * 1000
        
        # Trace booking creation
        langsmith_monitor.trace_node_execution(
            node_name="calendly_creator",
            session_id=session_id,
            inputs={'requestedDateTime': requested_datetime, 'phoneNumber': phone_number},
            outputs=booking_result,
            duration_ms=duration,
            success=booking_result.get('success', False),
            error=booking_result.get('error'),
            parent_trace=session_trace
        )
        
        return booking_result
    
    async def _send_confirmation(self, phone_number: str, booking_result: Dict[str, Any],
                                session_id: str, session_trace: Any) -> None:
        """Send booking confirmation SMS"""
        start_time = time.time()
        
        confirmation_result = send_confirmation_sms({
            'phoneNumber': phone_number,
            'confirmationDetails': booking_result.get('confirmationDetails', {}),
            'eventUrl': booking_result.get('eventUrl', ''),
            'sessionId': session_id
        })
        
        duration = (time.time() - start_time) * 1000
        
        # Trace confirmation SMS
        langsmith_monitor.trace_node_execution(
            node_name="send_confirmation_sms",
            session_id=session_id,
            inputs={'phoneNumber': phone_number, 'confirmationDetails': booking_result.get('confirmationDetails')},
            outputs=confirmation_result,
            duration_ms=duration,
            success=confirmation_result.get('messageSent', False),
            error=confirmation_result.get('error'),
            parent_trace=session_trace
        )
    
    async def _send_availability_response(self, phone_number: str, availability_result: Dict[str, Any],
                                         session_id: str, session_trace: Any) -> None:
        """Send availability alternatives to user"""
        # Implementation would use twilio_sender to send availability info
        pass
    
    async def _send_fallback_response(self, phone_number: str, user_message: str,
                                     session_id: str, session_trace: Any) -> None:
        """Send fallback response when processing fails"""
        start_time = time.time()
        
        fallback_result = send_fallback_response({
            'phoneNumber': phone_number,
            'userMessage': user_message,
            'sessionId': session_id,
            'failureReason': 'processing_error'
        })
        
        duration = (time.time() - start_time) * 1000
        
        # Trace fallback response
        langsmith_monitor.trace_node_execution(
            node_name="fallback_handler",
            session_id=session_id,
            inputs={'phoneNumber': phone_number, 'userMessage': user_message},
            outputs=fallback_result,
            duration_ms=duration,
            success=fallback_result.get('messageSent', False),
            error=fallback_result.get('error'),
            parent_trace=session_trace
        )
    
    async def _send_error_and_log(self, phone_number: str, error_type: str,
                                 session_id: str, context: Dict[str, Any]) -> None:
        """Send error SMS and log the error"""
        error_result = send_error_sms({
            'phoneNumber': phone_number,
            'errorType': error_type,
            'sessionId': session_id,
            'context': context
        })
        
        # Log the error
        sms_logger.log_sms_failure(
            failure_type=error_type,
            session_id=session_id,
            phone_number=phone_number,
            error_details=context,
            retry_count=0
        )

# Initialize orchestrator
orchestrator = ConversationOrchestrator()

@app.post("/webhook/twilio")
async def twilio_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Twilio SMS webhook endpoint
    Receives incoming SMS messages and processes them through the conversation flow
    """
    
    try:
        # Parse form data from Twilio
        form_data = await request.form()
        
        # Convert to our webhook model
        webhook_data = TwilioWebhook(
            MessageSid=form_data.get('MessageSid', ''),
            AccountSid=form_data.get('AccountSid', ''),
            From=form_data.get('From', ''),
            To=form_data.get('To', ''),
            Body=form_data.get('Body', ''),
            NumMedia=form_data.get('NumMedia', '0')
        )
        
        logger.info("Received SMS webhook", 
                   from_number=webhook_data.From,
                   message_body=webhook_data.Body,
                   message_sid=webhook_data.MessageSid)
        
        # Process in background to return quickly to Twilio
        background_tasks.add_task(orchestrator.process_sms, webhook_data)
        
        # Return success to Twilio
        return PlainTextResponse("OK", status_code=200)
    
    except Exception as e:
        logger.error("Webhook processing failed", error=str(e))
        raise HTTPException(status_code=500, detail="Webhook processing failed")

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "1.0.0"
    }

@app.get("/metrics")
async def metrics():
    """Basic metrics endpoint"""
    total_sessions = len(session_store)
    completed_sessions = sum(1 for s in session_store.values() if s.get('conversationState') == 'completed')
    
    return {
        "total_sessions": total_sessions,
        "completed_sessions": completed_sessions,
        "success_rate": completed_sessions / total_sessions if total_sessions > 0 else 0,
        "active_sessions": total_sessions - completed_sessions
    }

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    debug_mode = os.getenv("DEBUG_MODE", "false").lower() == "true"
    
    logger.info("Starting SMS Appointment Booking Agent", 
               port=port, 
               debug_mode=debug_mode)
    
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=debug_mode,
        log_level="info"
    )