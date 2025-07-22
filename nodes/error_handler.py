"""
Error Handler Node
Manages error responses and user-friendly error messaging via SMS
"""

import os
from typing import Dict, Any
from langsmith import traceable
import structlog
from datetime import datetime

# Import the WhatsApp sender
from .twilio_sender import TwilioWhatsAppSender

# Configure structured logging
logger = structlog.get_logger()

class ErrorHandler:
    def __init__(self):
        """Initialize error handler with WhatsApp capabilities"""
        self.whatsapp_sender = TwilioWhatsAppSender()
        logger.info("Error handler initialized")

    def get_error_message(self, error_type: str, context: Dict[str, Any] = None) -> str:
        """
        Get user-friendly error message based on error type
        
        Args:
            error_type: Type of error that occurred
            context: Additional context for personalized messages
        
        Returns:
            User-friendly error message
        """
        
        error_messages = {
            "phone_validation": "❌ I couldn't validate your phone number. Please make sure you're texting from a valid phone number.",
            
            "groq_processing": "🤔 I'm having trouble understanding your message right now. Could you please try rephrasing your appointment request?",
            
            "calendly_api": "📅 I'm experiencing issues connecting to the calendar system. Please try again in a few minutes.",
            
            "calendly_availability": "⏰ I couldn't check availability right now. The calendar system may be temporarily unavailable. Please try again shortly.",
            
            "calendly_booking": "📝 I encountered an issue while trying to book your appointment. Please try again or contact support.",
            
            "sms_delivery": "📱 There was an issue sending your message. If you don't receive a response, please try texting again.",
            
            "session_timeout": "⏱️ Your session has expired. Please start over by sending a new message with your appointment request.",
            
            "invalid_datetime": "📅 The date and time you provided doesn't seem valid. Please try again with a format like 'tomorrow at 2pm' or 'Friday at 10:30am'.",
            
            "past_datetime": "⏰ That time has already passed. Please choose a future date and time for your appointment.",
            
            "outside_business_hours": "🕘 We only schedule appointments Monday-Friday between 9 AM and 6 PM. Please choose a time within business hours.",
            
            "too_far_future": "📆 We can only schedule appointments up to 6 months in advance. Please choose an earlier date.",
            
            "general": "❌ Something went wrong. Please try again or contact support if the problem persists."
        }
        
        base_message = error_messages.get(error_type, error_messages["general"])
        
        # Add context-specific information if available
        if context:
            if error_type == "calendly_api" and context.get('retry_after'):
                base_message += f" You can try again in {context['retry_after']} minutes."
            
            elif error_type == "invalid_datetime" and context.get('suggested_format'):
                base_message += f" Try something like: {context['suggested_format']}"
        
        return base_message

    @traceable(
        name="send_error_sms",
        tags=["error", "sms", "user_communication"],
        metadata={"component": "error_handler"}
    )
    def send_error_sms(self, phone_number: str, error_type: str, 
                      session_id: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Send error message via SMS to user
        
        Args:
            phone_number: User's phone number
            error_type: Type of error that occurred
            session_id: Session identifier
            context: Additional error context
        
        Returns:
            Dict with SMS sending results
        """
        
        logger.info("Sending error SMS", 
                    error_type=error_type,
                    phone_number=phone_number,
                    session_id=session_id)
        
        try:
            # Get appropriate error message
            error_message = self.get_error_message(error_type, context)
            
            # Add helpful instructions based on error type
            if error_type in ["groq_processing", "invalid_datetime"]:
                error_message += "\n\nHere are some examples:\n• 'Tomorrow at 2pm'\n• 'Next Monday at 10am'\n• 'Friday afternoon'"
            
            elif error_type in ["calendly_api", "calendly_availability", "calendly_booking"]:
                error_message += "\n\nWe apologize for the inconvenience. Our team has been notified."
            
            # Send the error message
            result = self.whatsapp_sender.send_whatsapp(
                to_number=phone_number,
                message=error_message,
                session_id=session_id,
                message_type="error"
            )
            
            if result.get('messageSent'):
                logger.info("Error SMS sent successfully", 
                           error_type=error_type,
                           session_id=session_id)
            else:
                logger.error("Failed to send error SMS", 
                           error=result.get('error'),
                           session_id=session_id)
            
            return result
        
        except Exception as e:
            logger.error("Error handler exception", 
                        error=str(e),
                        error_type=error_type,
                        session_id=session_id)
            
            return {
                "messageSent": False,
                "error": f"Error handler failed: {str(e)}",
                "sessionId": session_id
            }

# Global error handler instance
error_handler = ErrorHandler()

@traceable(
    name="send_error_sms",
    tags=["error_handling", "sms"],
    metadata={"component": "error_sms"}
)
def send_error_sms(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for sending error SMS messages
    
    Args:
        inputs: Dict containing phoneNumber, errorType, sessionId, context
    
    Returns:
        Dict with SMS sending results
    """
    
    phone_number = inputs.get('phoneNumber')
    error_type = inputs.get('errorType', 'general')
    session_id = inputs.get('sessionId', '')
    context = inputs.get('context', {})
    
    if not phone_number:
        logger.error("Cannot send error SMS: missing phone number", 
                    session_id=session_id)
        return {
            "messageSent": False,
            "error": "Missing phone number",
            "sessionId": session_id
        }
    
    return error_handler.send_error_sms(
        phone_number=phone_number,
        error_type=error_type,
        session_id=session_id,
        context=context
    )

@traceable(
    name="log_error",
    tags=["logging", "error_tracking"],
    metadata={"component": "error_logging"}
)
def log_error(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Log error details for monitoring and debugging
    
    Args:
        inputs: Dict containing error details
    
    Returns:
        Dict with logging results
    """
    
    error_type = inputs.get('errorType', 'unknown')
    error_message = inputs.get('error', '')
    session_id = inputs.get('sessionId', '')
    phone_number = inputs.get('phoneNumber', '')
    context = inputs.get('context', {})
    node_name = inputs.get('nodeName', '')
    
    # Log the error with full context
    logger.error("SMS Agent Error", 
                error_type=error_type,
                error_message=error_message,
                session_id=session_id,
                phone_number=phone_number,
                node_name=node_name,
                context=context,
                timestamp=datetime.utcnow().isoformat())
    
    # Could also send to external monitoring service here
    # (e.g., Sentry, DataDog, CloudWatch)
    
    return {
        "logged": True,
        "timestamp": datetime.utcnow().isoformat(),
        "sessionId": session_id
    }

# Test function
if __name__ == "__main__":
    # Test error message generation
    test_error_types = [
        "phone_validation",
        "groq_processing", 
        "calendly_api",
        "invalid_datetime",
        "outside_business_hours"
    ]
    
    print("Testing error message generation...")
    for error_type in test_error_types:
        message = error_handler.get_error_message(error_type)
        print(f"\n{error_type}: {message}")
    
    # Test with context
    print("\nTesting with context...")
    context_message = error_handler.get_error_message(
        "invalid_datetime", 
        {"suggested_format": "Monday at 3pm"}
    )
    print(f"With context: {context_message}")
    
    # Test error SMS sending (requires valid Twilio credentials)
    print("\nTesting error SMS sending...")
    result = send_error_sms({
        "phoneNumber": "+1234567890",  # Replace with test number
        "errorType": "groq_processing",
        "sessionId": "test-error-session"
    })
    print(f"SMS result: {result}")
