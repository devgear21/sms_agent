"""
Twilio SMS Sender Node
Handles sending SMS messages with retry logic and LangSmith tracing
Supports welcome messages, confirmations, and error notifications
"""

import os
from twilio.rest import Client
from twilio.base.exceptions import TwilioException
from langsmith import traceable
from typing import Dict, Any, Optional
import structlog
from datetime import datetime

# Configure structured logging
logger = structlog.get_logger()

class SMSSendingError(Exception):
    """Custom exception for SMS sending errors"""
    pass

class TwilioSMSSender:
    def __init__(self):
        """Initialize Twilio client with credentials from environment"""
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.from_number = os.getenv('TWILIO_PHONE_NUMBER')
        
        if not all([self.account_sid, self.auth_token, self.from_number]):
            raise ValueError("Missing required Twilio environment variables")
        
        self.client = Client(self.account_sid, self.auth_token)
        logger.info("Twilio SMS sender initialized", from_number=self.from_number)

    @traceable(
        name="send_sms",
        tags=["sms", "twilio", "communication"],
        metadata={"component": "twilio_sender"}
    )
    def send_sms(self, to_number: str, message: str, session_id: str, 
                 message_type: str = "general") -> Dict[str, Any]:
        """
        Send SMS message via Twilio
        
        Args:
            to_number: Recipient phone number in E.164 format
            message: SMS message content
            session_id: Session identifier for tracking
            message_type: Type of message (welcome, confirmation, error, etc.)
        
        Returns:
            Dict with success status and message details
        """
        
        logger.info("Attempting to send SMS", 
                    to_number=to_number,
                    message_type=message_type,
                    session_id=session_id,
                    message_length=len(message))
        
        try:
            # Send SMS via Twilio
            message_obj = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to_number
            )
            
            logger.info("SMS sent successfully", 
                        message_sid=message_obj.sid,
                        to_number=to_number,
                        message_type=message_type,
                        session_id=session_id,
                        status=message_obj.status)
            
            return {
                "messageSent": True,
                "messageId": message_obj.sid,
                "status": message_obj.status,
                "to": to_number,
                "messageType": message_type,
                "sessionId": session_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except TwilioException as e:
            error_msg = f"Twilio error: {e.msg}"
            logger.error("Twilio SMS sending failed", 
                        error=str(e),
                        error_code=getattr(e, 'code', 'unknown'),
                        to_number=to_number,
                        session_id=session_id)
            
            return {
                "messageSent": False,
                "error": error_msg,
                "errorCode": getattr(e, 'code', 'unknown'),
                "to": to_number,
                "messageType": message_type,
                "sessionId": session_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            error_msg = f"Unexpected SMS error: {str(e)}"
            logger.error("Unexpected SMS sending error", 
                        error=str(e),
                        to_number=to_number,
                        session_id=session_id)
            
            return {
                "messageSent": False,
                "error": error_msg,
                "to": to_number,
                "messageType": message_type,
                "sessionId": session_id,
                "timestamp": datetime.utcnow().isoformat()
            }

# Global SMS sender instance
sms_sender = TwilioSMSSender()

@traceable(
    name="send_welcome_sms",
    tags=["sms", "welcome", "onboarding"],
    metadata={"component": "welcome_sms"}
)
def send_welcome_sms(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send welcome/greeting SMS to new users
    
    Args:
        inputs: Dict containing phoneNumber and sessionId
    
    Returns:
        Dict with sending results
    """
    
    phone_number = inputs.get('phoneNumber')
    session_id = inputs.get('sessionId')
    
    welcome_message = """👋 Welcome to our appointment booking service!

I'm here to help you schedule an appointment. 

Please tell me when you'd like to meet. You can say things like:
• "Tomorrow at 2pm"
• "Next Monday morning"
• "Friday afternoon"

What works best for you?"""
    
    return sms_sender.send_sms(
        to_number=phone_number,
        message=welcome_message,
        session_id=session_id,
        message_type="welcome"
    )

@traceable(
    name="send_confirmation_sms",
    tags=["sms", "confirmation", "booking"],
    metadata={"component": "confirmation_sms"}
)
def send_confirmation_sms(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send appointment confirmation SMS
    
    Args:
        inputs: Dict containing phoneNumber, confirmationDetails, eventUrl, sessionId
    
    Returns:
        Dict with sending results
    """
    
    phone_number = inputs.get('phoneNumber')
    session_id = inputs.get('sessionId')
    confirmation_details = inputs.get('confirmationDetails', {})
    event_url = inputs.get('eventUrl', '')
    
    # Extract appointment details
    appointment_time = confirmation_details.get('start_time', 'TBD')
    appointment_date = confirmation_details.get('date', 'TBD')
    event_name = confirmation_details.get('event_name', 'Appointment')
    
    confirmation_message = f"""✅ Your appointment is confirmed!

📅 {event_name}
🗓️ {appointment_date}
🕐 {appointment_time}

🔗 Add to calendar: {event_url}

Need to reschedule? Reply with "reschedule" or visit the link above.

We'll send you a reminder 24 hours before your appointment."""
    
    return sms_sender.send_sms(
        to_number=phone_number,
        message=confirmation_message,
        session_id=session_id,
        message_type="confirmation"
    )

@traceable(
    name="send_availability_response",
    tags=["sms", "availability", "scheduling"],
    metadata={"component": "availability_sms"}
)
def send_availability_response(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Send availability information and alternatives
    
    Args:
        inputs: Dict containing phoneNumber, availableSlots, sessionId
    
    Returns:
        Dict with sending results
    """
    
    phone_number = inputs.get('phoneNumber')
    session_id = inputs.get('sessionId')
    available_slots = inputs.get('availableSlots', [])
    suggested_alternatives = inputs.get('suggestedAlternatives', [])
    
    if available_slots:
        # Build message with available slots
        slots_text = "\n".join([f"• {slot}" for slot in available_slots[:5]])  # Limit to 5 slots
        
        message = f"""⏰ I found these available times:

{slots_text}

Reply with the number of your preferred time slot (e.g., "1" for the first option) or suggest a different time."""
        
    elif suggested_alternatives:
        # No exact match, show alternatives
        alternatives_text = "\n".join([f"• {alt}" for alt in suggested_alternatives[:3]])
        
        message = f"""❌ Sorry, that time isn't available. 

How about these alternatives:

{alternatives_text}

Please choose one or suggest another time that works for you."""
        
    else:
        # No availability found
        message = """❌ I couldn't find any available times for your request.

Could you please suggest a different date or time? I'll check what's available and get back to you right away."""
    
    return sms_sender.send_sms(
        to_number=phone_number,
        message=message,
        session_id=session_id,
        message_type="availability"
    )

# Test function
if __name__ == "__main__":
    # Test SMS sending (requires valid Twilio credentials)
    test_inputs = {
        "phoneNumber": "+1234567890",  # Replace with your test number
        "sessionId": "test-session-123"
    }
    
    print("Testing welcome SMS...")
    result = send_welcome_sms(test_inputs)
    print(f"Result: {result}")
    
    # Test confirmation
    confirmation_inputs = {
        **test_inputs,
        "confirmationDetails": {
            "start_time": "2:00 PM",
            "date": "January 25, 2025",
            "event_name": "Consultation"
        },
        "eventUrl": "https://calendly.com/event/abc123"
    }
    
    print("\nTesting confirmation SMS...")
    result = send_confirmation_sms(confirmation_inputs)
    print(f"Result: {result}")
