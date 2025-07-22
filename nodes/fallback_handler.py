"""
Fallback Handler Node
Provides fallback responses when AI processing fails or encounters issues
"""

import os
import random
from typing import Dict, Any, List
from langsmith import traceable
import structlog
from datetime import datetime

# Import the SMS sender
from .twilio_sender import TwilioSMSSender

# Configure structured logging
logger = structlog.get_logger()

class FallbackHandler:
    def __init__(self):
        """Initialize fallback handler with SMS capabilities"""
        self.sms_sender = TwilioSMSSender()
        logger.info("Fallback handler initialized")

    def get_fallback_responses(self) -> Dict[str, List[str]]:
        """
        Get collection of fallback responses organized by scenario
        
        Returns:
            Dict mapping scenarios to lists of possible responses
        """
        
        return {
            "general": [
                "I'm having a bit of trouble understanding your request. Could you please tell me when you'd like to schedule your appointment?",
                
                "Let me help you book an appointment! Please tell me your preferred date and time, like 'tomorrow at 2pm' or 'Friday morning'.",
                
                "I'd be happy to help schedule your appointment. What day and time work best for you?",
                
                "Sorry, I didn't quite catch that. Could you please tell me when you'd like to meet? For example: 'Next Monday at 10am'",
            ],
            
            "date_time_unclear": [
                "I want to make sure I get your appointment time right. Could you be more specific about the date and time you prefer?",
                
                "I need a bit more information about when you'd like to meet. Please tell me the specific day and time you have in mind.",
                
                "To book your appointment, I'll need the exact date and time. Could you tell me something like 'Tuesday at 3pm' or 'tomorrow morning at 10am'?",
            ],
            
            "processing_error": [
                "I'm experiencing some technical difficulties right now. Could you please try sending your appointment request again?",
                
                "Something went wrong on my end. Please resend your message with your preferred appointment time.",
                
                "I had a temporary issue processing your request. Could you please tell me again when you'd like to schedule your appointment?",
            ],
            
            "ambiguous_request": [
                "I want to make sure I understand correctly. Are you looking to:\n• Book a new appointment\n• Reschedule an existing appointment\n• Cancel an appointment\n\nPlease let me know!",
                
                "I can help with appointments! Could you clarify what you'd like to do and when you'd prefer to meet?",
                
                "I'm here to help with your appointment. Please tell me exactly what you need and your preferred time.",
            ],
            
            "encouragement": [
                "No worries! Let's try this step by step. When would you like to schedule your appointment?",
                
                "That's okay! I'm here to help. Just tell me your preferred day and time for the appointment.",
                
                "Don't worry, we'll get this sorted out. What date and time work best for your schedule?",
            ]
        }

    def get_helpful_examples(self) -> List[str]:
        """Get examples of well-formatted appointment requests"""
        return [
            "Tomorrow at 2pm",
            "Next Monday at 10:30am", 
            "Friday afternoon around 3pm",
            "This Thursday at 11am",
            "January 25th at 1:30pm",
            "Next week Wednesday morning"
        ]

    @traceable(
        name="generate_fallback_response",
        tags=["fallback", "conversation", "recovery"],
        metadata={"component": "fallback_handler"}
    )
    def generate_fallback_response(self, user_message: str, session_id: str,
                                  failure_reason: str = "general",
                                  include_examples: bool = True) -> str:
        """
        Generate an appropriate fallback response
        
        Args:
            user_message: Original user message that failed to process
            session_id: Session identifier
            failure_reason: Reason for fallback (general, processing_error, etc.)
            include_examples: Whether to include helpful examples
        
        Returns:
            Fallback response message
        """
        
        logger.info("Generating fallback response", 
                    failure_reason=failure_reason,
                    message_length=len(user_message),
                    session_id=session_id)
        
        responses = self.get_fallback_responses()
        
        # Select appropriate response category
        if failure_reason in responses:
            response_list = responses[failure_reason]
        else:
            response_list = responses["general"]
        
        # Randomly select a response to avoid repetition
        base_response = random.choice(response_list)
        
        # Add helpful examples if requested
        if include_examples and failure_reason in ["general", "date_time_unclear"]:
            examples = self.get_helpful_examples()
            selected_examples = random.sample(examples, min(3, len(examples)))
            
            examples_text = "\n\nHere are some examples:\n" + "\n".join([f"• {ex}" for ex in selected_examples])
            base_response += examples_text
        
        # Add encouragement for processing errors
        if failure_reason == "processing_error":
            encouragement = random.choice(self.get_fallback_responses()["encouragement"])
            base_response += f"\n\n{encouragement}"
        
        return base_response

    @traceable(
        name="send_fallback_sms",
        tags=["fallback", "sms", "recovery"],
        metadata={"component": "fallback_sms"}
    )
    def send_fallback_sms(self, phone_number: str, user_message: str, 
                         session_id: str, failure_reason: str = "general") -> Dict[str, Any]:
        """
        Send fallback response via SMS
        
        Args:
            phone_number: User's phone number
            user_message: Original message that failed
            session_id: Session identifier
            failure_reason: Reason for fallback
        
        Returns:
            Dict with SMS sending results
        """
        
        logger.info("Sending fallback SMS", 
                    failure_reason=failure_reason,
                    phone_number=phone_number,
                    session_id=session_id)
        
        try:
            # Generate appropriate fallback response
            fallback_message = self.generate_fallback_response(
                user_message=user_message,
                session_id=session_id,
                failure_reason=failure_reason,
                include_examples=True
            )
            
            # Send the fallback message
            result = self.sms_sender.send_sms(
                to_number=phone_number,
                message=fallback_message,
                session_id=session_id,
                message_type="fallback"
            )
            
            if result.get('messageSent'):
                logger.info("Fallback SMS sent successfully", 
                           failure_reason=failure_reason,
                           session_id=session_id)
            else:
                logger.error("Failed to send fallback SMS", 
                           error=result.get('error'),
                           session_id=session_id)
            
            return result
        
        except Exception as e:
            logger.error("Fallback handler exception", 
                        error=str(e),
                        failure_reason=failure_reason,
                        session_id=session_id)
            
            return {
                "messageSent": False,
                "error": f"Fallback handler failed: {str(e)}",
                "sessionId": session_id
            }

    @traceable(
        name="detect_intent_from_failed_message",
        tags=["intent", "recovery", "analysis"],
        metadata={"component": "intent_detection"}
    )
    def detect_intent_from_failed_message(self, user_message: str) -> str:
        """
        Try to detect user intent from a message that failed AI processing
        
        Args:
            user_message: User's message
        
        Returns:
            Detected intent or failure reason
        """
        
        message_lower = user_message.lower().strip()
        
        # Keywords for different intents
        booking_keywords = ["book", "schedule", "appointment", "meet", "available", "time", "date"]
        cancel_keywords = ["cancel", "delete", "remove", "stop"]
        reschedule_keywords = ["reschedule", "change", "move", "different time"]
        help_keywords = ["help", "how", "what", "?"]
        
        # Check for time indicators
        time_indicators = ["tomorrow", "today", "monday", "tuesday", "wednesday", "thursday", 
                          "friday", "saturday", "sunday", "morning", "afternoon", "evening",
                          "am", "pm", "next", "this", "week"]
        
        # Detect intent
        if any(keyword in message_lower for keyword in cancel_keywords):
            return "cancellation"
        elif any(keyword in message_lower for keyword in reschedule_keywords):
            return "rescheduling"
        elif any(keyword in message_lower for keyword in help_keywords):
            return "help_request"
        elif any(keyword in message_lower for keyword in booking_keywords) or \
             any(indicator in message_lower for indicator in time_indicators):
            return "date_time_unclear"
        else:
            return "ambiguous_request"

# Global fallback handler instance
fallback_handler = FallbackHandler()

@traceable(
    name="send_fallback_response",
    tags=["fallback", "recovery"],
    metadata={"component": "fallback_response"}
)
def send_fallback_response(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for sending fallback responses
    
    Args:
        inputs: Dict containing phoneNumber, userMessage, sessionId
    
    Returns:
        Dict with fallback response results
    """
    
    phone_number = inputs.get('phoneNumber')
    user_message = inputs.get('userMessage', '')
    session_id = inputs.get('sessionId', '')
    failure_reason = inputs.get('failureReason', 'general')
    
    if not phone_number:
        logger.error("Cannot send fallback response: missing phone number", 
                    session_id=session_id)
        return {
            "messageSent": False,
            "error": "Missing phone number",
            "sessionId": session_id
        }
    
    # Try to detect intent if no specific failure reason provided
    if failure_reason == "general" and user_message:
        detected_intent = fallback_handler.detect_intent_from_failed_message(user_message)
        if detected_intent != "general":
            failure_reason = detected_intent
    
    return fallback_handler.send_fallback_sms(
        phone_number=phone_number,
        user_message=user_message,
        session_id=session_id,
        failure_reason=failure_reason
    )

@traceable(
    name="generate_help_response",
    tags=["help", "guidance"],
    metadata={"component": "help_response"}
)
def generate_help_response(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Generate helpful guidance for users
    
    Args:
        inputs: Dict containing phoneNumber, sessionId
    
    Returns:
        Dict with help response results
    """
    
    phone_number = inputs.get('phoneNumber')
    session_id = inputs.get('sessionId', '')
    
    help_message = """📋 I can help you with appointments!

Here's what I can do:
• Book new appointments
• Check availability
• Send confirmations

To book an appointment, just tell me when you'd like to meet:

Examples:
• "Tomorrow at 2pm"
• "Next Monday morning"
• "Friday at 3:30pm"
• "This Thursday at 10am"

What would you like to schedule?"""
    
    try:
        result = fallback_handler.sms_sender.send_sms(
            to_number=phone_number,
            message=help_message,
            session_id=session_id,
            message_type="help"
        )
        
        return result
    
    except Exception as e:
        logger.error("Help response failed", 
                    error=str(e),
                    session_id=session_id)
        
        return {
            "messageSent": False,
            "error": f"Help response failed: {str(e)}",
            "sessionId": session_id
        }

# Test function
if __name__ == "__main__":
    # Test fallback response generation
    test_messages = [
        "sdfjksdjf",  # Gibberish
        "cancel my thing",  # Cancellation intent
        "I want to meet sometime",  # Vague booking request
        "help me please",  # Help request
        "change my appointment time"  # Reschedule request
    ]
    
    print("Testing fallback response generation...")
    for i, message in enumerate(test_messages):
        print(f"\nTest {i+1}: '{message}'")
        
        # Detect intent
        intent = fallback_handler.detect_intent_from_failed_message(message)
        print(f"Detected intent: {intent}")
        
        # Generate response
        response = fallback_handler.generate_fallback_response(
            user_message=message,
            session_id=f"test-{i+1}",
            failure_reason=intent
        )
        print(f"Response: {response[:100]}...")
    
    # Test SMS sending (requires valid Twilio credentials)
    print("\nTesting fallback SMS sending...")
    result = send_fallback_response({
        "phoneNumber": "+1234567890",  # Replace with test number
        "userMessage": "I want to meet sometime",
        "sessionId": "test-fallback-session"
    })
    print(f"SMS result: {result}")
