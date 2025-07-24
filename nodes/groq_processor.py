"""
Groq LLaMA Conversation Processor Node
Handles natural language processing for appointment booking conversations
Extracts date/time preferences and manages conversation flow
"""

import os
import re
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
from langchain_groq import ChatGroq
from langchain.schema import HumanMessage, SystemMessage
from langsmith import traceable
import structlog
import json

# Configure structured logging
logger = structlog.get_logger()

class ConversationProcessor:
    def __init__(self):
        """Initialize Groq LLaMA client"""
        self.groq_api_key = os.getenv('GROQ_API_KEY')
        if not self.groq_api_key:
            raise ValueError("GROQ_API_KEY environment variable is required")
        
        self.llm = ChatGroq(
            api_key=self.groq_api_key,
            model="llama-3.1-70b-versatile",
            temperature=0.3,
            max_tokens=1024
        )
        
        logger.info("Groq LLaMA processor initialized")

    def get_system_prompt(self) -> str:
        """Get the system prompt for appointment booking conversations"""
        return """You are a helpful appointment booking assistant. Your job is to:

1. Extract date and time preferences from user messages
2. Determine if you have enough information to check availability
3. Provide friendly, professional responses
4. Handle rescheduling and cancellation requests

CRITICAL: Your response must be ONLY valid JSON with no extra text, markdown, or code blocks.

RESPONSE FORMAT: Always respond with valid JSON in this exact format:
{
    "extracted_datetime": "YYYY-MM-DD HH:MM" or null,
    "response_message": "Your response to the user",
    "next_state": "collecting_preferences|checking_availability|confirming|completed",
    "needs_more_info": true/false,
    "confidence": 0.0-1.0,
    "extracted_elements": {
        "date_mentioned": "text that indicates date",
        "time_mentioned": "text that indicates time",
        "timezone": "inferred timezone or null"
    }
}

EXAMPLES:

User: "Tomorrow at 2pm"
Response: {"extracted_datetime": "2025-01-23 14:00", "response_message": "Great! I'll check if tomorrow at 2 PM is available for you.", "next_state": "checking_availability", "needs_more_info": false, "confidence": 0.9, "extracted_elements": {"date_mentioned": "tomorrow", "time_mentioned": "2pm", "timezone": null}}

User: "I need to meet next week"
Response: {"extracted_datetime": null, "response_message": "I'd be happy to help you schedule for next week! What day and time would work best for you?", "next_state": "collecting_preferences", "needs_more_info": true, "confidence": 0.3, "extracted_elements": {"date_mentioned": "next week", "time_mentioned": null, "timezone": null}}

RULES:
- Always assume Eastern Time if no timezone specified
- Convert relative dates (today, tomorrow, next Monday) to absolute dates
- If date or time is unclear, ask for clarification
- Be conversational but concise
- Handle cancellation/reschedule requests appropriately
- Current date/time context: {current_datetime}
- IMPORTANT: Return ONLY the JSON object, no additional text or formatting"""

    @traceable(
        name="groq_llm_processing",
        tags=["llm", "groq", "conversation", "nlu"],
        metadata={"component": "groq_processor"}
    )
    def process_message(self, user_message: str, conversation_state: str, 
                       session_id: str, context: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Process user message using Groq LLaMA for appointment booking
        
        Args:
            user_message: The user's SMS message
            conversation_state: Current conversation state
            session_id: Session identifier
            context: Additional context (previous messages, etc.)
        
        Returns:
            Dict with extracted information and response
        """
        
        logger.info("Processing user message with Groq", 
                    message=user_message,
                    state=conversation_state,
                    session_id=session_id)
        
        try:
            # Get current datetime for context
            current_datetime = datetime.now().strftime("%Y-%m-%d %H:%M Eastern Time")
            
            # Build system prompt with current datetime
            system_prompt = self.get_system_prompt().format(current_datetime=current_datetime)
            
            # Add conversation context
            if context and context.get('previous_messages'):
                system_prompt += f"\n\nPrevious conversation context: {context['previous_messages']}"
            
            # Create messages for LLM
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=f"User message: {user_message}\nCurrent state: {conversation_state}")
            ]
            
            # Call Groq LLaMA
            response = self.llm.invoke(messages)
            response_content = response.content.strip()
            
            logger.info("Groq LLM response received", 
                       response_length=len(response_content),
                       session_id=session_id)
            
            # Parse JSON response
            try:
                # Aggressive JSON cleaning to handle newlines and formatting issues
                cleaned_response = response_content.strip()
                
                # Remove markdown code blocks if present
                if cleaned_response.startswith('```json'):
                    cleaned_response = cleaned_response[7:]  # Remove ```json
                if cleaned_response.endswith('```'):
                    cleaned_response = cleaned_response[:-3]  # Remove ```
                
                # Remove any leading/trailing whitespace again
                cleaned_response = cleaned_response.strip()
                
                # AGGRESSIVE: Remove all problematic newlines and extra spaces
                # Replace newlines with spaces in JSON strings
                cleaned_response = re.sub(r'\n\s*"', ' "', cleaned_response)  # newline before quotes
                cleaned_response = re.sub(r'"\s*\n\s*', '" ', cleaned_response)  # newline after quotes
                cleaned_response = re.sub(r':\s*\n\s*', ': ', cleaned_response)  # newline after colons
                cleaned_response = re.sub(r',\s*\n\s*', ', ', cleaned_response)  # newline after commas
                cleaned_response = re.sub(r'{\s*\n\s*', '{ ', cleaned_response)  # newline after opening brace
                cleaned_response = re.sub(r'\s*\n\s*}', ' }', cleaned_response)  # newline before closing brace
                
                # Replace multiple spaces with single space
                cleaned_response = re.sub(r'\s+', ' ', cleaned_response)
                
                logger.info("Attempting to parse JSON response", 
                           original_length=len(response_content),
                           cleaned_length=len(cleaned_response),
                           first_100_chars=cleaned_response[:100],
                           session_id=session_id)
                
                parsed_response = json.loads(cleaned_response)
                
                # Validate required fields
                required_fields = ['extracted_datetime', 'response_message', 'next_state', 'needs_more_info']
                for field in required_fields:
                    if field not in parsed_response:
                        raise ValueError(f"Missing required field: {field}")
                
                # Validate required fields
                required_fields = ['extracted_datetime', 'response_message', 'next_state', 'needs_more_info']
                for field in required_fields:
                    if field not in parsed_response:
                        raise ValueError(f"Missing required field: {field}")
                
                # Add metadata
                parsed_response['sessionId'] = session_id
                parsed_response['timestamp'] = datetime.utcnow().isoformat()
                parsed_response['original_message'] = user_message
                
                logger.info("Message processing successful", 
                           extracted_datetime=parsed_response.get('extracted_datetime'),
                           next_state=parsed_response.get('next_state'),
                           needs_more_info=parsed_response.get('needs_more_info'),
                           session_id=session_id)
                
                return parsed_response
                
            except json.JSONDecodeError as e:
                logger.error("Failed to parse LLM JSON response", 
                           error=str(e),
                           response_content=response_content,
                           cleaned_response=cleaned_response,
                           response_length=len(response_content),
                           session_id=session_id)
                
                # BACKUP APPROACH: Try to extract JSON object manually
                try:
                    # Find JSON object boundaries
                    start_idx = response_content.find('{')
                    end_idx = response_content.rfind('}')
                    
                    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
                        json_part = response_content[start_idx:end_idx + 1]
                        
                        # Apply aggressive cleaning to just the JSON part
                        json_part = re.sub(r'\n\s*', ' ', json_part)  # Replace all newlines with spaces
                        json_part = re.sub(r'\s+', ' ', json_part)    # Replace multiple spaces with single
                        
                        logger.info("Attempting backup JSON parsing", 
                                   backup_json=json_part[:100],
                                   session_id=session_id)
                        
                        parsed_response = json.loads(json_part)
                        
                        # Validate required fields
                        required_fields = ['extracted_datetime', 'response_message', 'next_state', 'needs_more_info']
                        for field in required_fields:
                            if field not in parsed_response:
                                raise ValueError(f"Missing required field: {field}")
                        
                        logger.info("Backup JSON parsing successful!", session_id=session_id)
                        
                    else:
                        raise ValueError("No valid JSON object found")
                        
                except Exception as backup_error:
                    logger.error("Backup JSON parsing also failed", 
                               error=str(backup_error),
                               session_id=session_id)
                    
                    # Try to extract a simple response if possible
                    fallback_message = "I'd be happy to help you schedule an appointment! Could you please tell me what date and time you'd prefer?"
                    
                    # Look for a response_message in the malformed JSON
                    try:
                        if '"response_message"' in response_content:
                            # Try to extract just the response message
                            match = re.search(r'"response_message"\s*:\s*"([^"]*)"', response_content)
                            if match:
                                fallback_message = match.group(1)
                    except Exception:
                        pass
                    
                    # Fallback response
                    return self._create_fallback_response(user_message, session_id, fallback_message)
            
        except Exception as e:
            logger.error("Groq processing error", 
                        error=str(e),
                        user_message=user_message,
                        session_id=session_id)
            
            return self._create_fallback_response(user_message, session_id,
                                                "I'm experiencing some technical difficulties. Please try rephrasing your request.")

    def _create_fallback_response(self, user_message: str, session_id: str, 
                                 fallback_message: str) -> Dict[str, Any]:
        """Create a fallback response when LLM processing fails"""
        return {
            "extracted_datetime": None,
            "response_message": fallback_message,
            "next_state": "collecting_preferences",
            "needs_more_info": True,
            "confidence": 0.0,
            "sessionId": session_id,
            "timestamp": datetime.utcnow().isoformat(),
            "original_message": user_message,
            "fallback": True,
            "extracted_elements": {
                "date_mentioned": None,
                "time_mentioned": None,
                "timezone": None
            }
        }

    @traceable(
        name="datetime_validation",
        tags=["validation", "datetime"],
        metadata={"component": "datetime_validator"}
    )
    def validate_extracted_datetime(self, datetime_str: str) -> Dict[str, Any]:
        """
        Validate and normalize extracted datetime
        
        Args:
            datetime_str: Datetime string in format "YYYY-MM-DD HH:MM"
        
        Returns:
            Dict with validation results and normalized datetime
        """
        
        try:
            # Parse the datetime
            parsed_dt = datetime.strptime(datetime_str, "%Y-%m-%d %H:%M")
            
            # Check if it's in the past
            now = datetime.now()
            if parsed_dt < now:
                return {
                    "valid": False,
                    "error": "Cannot book appointments in the past",
                    "suggested_fix": "Please choose a future date and time"
                }
            
            # Check if it's too far in the future (e.g., more than 6 months)
            six_months_later = now + timedelta(days=180)
            if parsed_dt > six_months_later:
                return {
                    "valid": False,
                    "error": "Cannot book appointments more than 6 months in advance",
                    "suggested_fix": "Please choose a date within the next 6 months"
                }
            
            # Check business hours (9 AM to 6 PM)
            if parsed_dt.hour < 9 or parsed_dt.hour >= 18:
                return {
                    "valid": False,
                    "error": "Appointments are only available between 9 AM and 6 PM",
                    "suggested_fix": "Please choose a time between 9 AM and 6 PM"
                }
            
            # Check weekdays only
            if parsed_dt.weekday() >= 5:  # Saturday = 5, Sunday = 6
                return {
                    "valid": False,
                    "error": "Appointments are only available Monday through Friday",
                    "suggested_fix": "Please choose a weekday"
                }
            
            return {
                "valid": True,
                "normalized_datetime": parsed_dt.isoformat(),
                "formatted_display": parsed_dt.strftime("%A, %B %d, %Y at %I:%M %p")
            }
            
        except ValueError as e:
            return {
                "valid": False,
                "error": f"Invalid datetime format: {str(e)}",
                "suggested_fix": "Please provide date and time in a clear format"
            }

# Global processor instance
processor = ConversationProcessor()

@traceable(
    name="process_user_message",
    tags=["conversation", "processing", "appointment"],
    metadata={"component": "message_processor"}
)
def process_user_message(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for processing user messages
    
    Args:
        inputs: Dict containing userMessage, conversationState, sessionId
    
    Returns:
        Dict with processing results
    """
    
    user_message = inputs.get('userMessage', '')
    conversation_state = inputs.get('conversationState', 'new')
    session_id = inputs.get('sessionId', '')
    context = inputs.get('context', {})
    
    # Process with Groq LLaMA
    result = processor.process_message(
        user_message=user_message,
        conversation_state=conversation_state,
        session_id=session_id,
        context=context
    )
    
    # If datetime was extracted, validate it
    if result.get('extracted_datetime'):
        validation = processor.validate_extracted_datetime(result['extracted_datetime'])
        
        if not validation.get('valid'):
            # Override response with validation error
            result['response_message'] = f"{validation['error']}. {validation['suggested_fix']}"
            result['extracted_datetime'] = None
            result['needs_more_info'] = True
            result['next_state'] = 'collecting_preferences'
            result['validation_error'] = validation['error']
    
    return result

# Test function
if __name__ == "__main__":
    # Test message processing
    test_messages = [
        "I want to book an appointment tomorrow at 2pm",
        "Can we meet next Monday morning?",
        "I need to reschedule my appointment",
        "Friday at 3:30 PM would be perfect",
        "How about tonight at 9pm?",  # Should fail validation
    ]
    
    print("Testing Groq message processing...")
    for i, message in enumerate(test_messages):
        print(f"\nTest {i+1}: '{message}'")
        result = process_user_message({
            "userMessage": message,
            "conversationState": "collecting_preferences",
            "sessionId": f"test-session-{i+1}"
        })
        print(f"Extracted datetime: {result.get('extracted_datetime')}")
        print(f"Response: {result.get('response_message')}")
        print(f"Needs more info: {result.get('needs_more_info')}")
        print(f"Next state: {result.get('next_state')}")
