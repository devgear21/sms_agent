"""
Phone Number Validation Node
Validates inbound phone numbers using libphonenumber and creates session IDs
Instrumented with LangSmith tracing
"""

import uuid
import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat, carrier
from langsmith import traceable
from typing import Dict, Any, Tuple
import structlog
import os

# Configure structured logging
logger = structlog.get_logger()

class PhoneValidationError(Exception):
    """Custom exception for phone validation errors"""
    pass

@traceable(
    name="phone_validation",
    tags=["validation", "phone", "input"],
    metadata={"component": "phone_validator"}
)
def validate_phone_number(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validates phone number from Twilio webhook and creates session
    
    Args:
        inputs: Dict containing 'From' (phone number) and 'Body' (SMS content)
    
    Returns:
        Dict with phoneNumber, isValid, sessionId, and normalized data
    """
    
    # Generate unique session ID
    session_id = str(uuid.uuid4())
    
    # Extract phone number from Twilio webhook
    raw_phone = inputs.get('From', '')
    sms_body = inputs.get('Body', '')
    
    logger.info("Processing phone validation", 
                raw_phone=raw_phone, 
                session_id=session_id,
                message_length=len(sms_body))
    
    try:
        # Parse phone number with libphonenumber
        # Use None to auto-detect region, fallback to US for numbers without country code
        try:
            parsed_number = phonenumbers.parse(raw_phone, None)
        except NumberParseException:
            # If parsing with None fails, try with US region for local numbers
            parsed_number = phonenumbers.parse(raw_phone, "US")
        
        # Validate the number
        is_valid = phonenumbers.is_valid_number(parsed_number)
        
        if not is_valid:
            logger.warning("Invalid phone number", 
                          raw_phone=raw_phone, 
                          session_id=session_id)
            return {
                "phoneNumber": raw_phone,
                "isValid": False,
                "sessionId": session_id,
                "error": "Invalid phone number format",
                "userMessage": sms_body
            }
        
        # Format to E.164 standard
        formatted_phone = phonenumbers.format_number(parsed_number, PhoneNumberFormat.E164)
        
        # Extract additional metadata
        region_code = phonenumbers.region_code_for_number(parsed_number)
        
        # Try to get carrier name, but don't fail if it doesn't work
        try:
            carrier_name = carrier.name_for_number(parsed_number, "en")
        except Exception as e:
            logger.warning("Could not get carrier name", error=str(e), phone=formatted_phone)
            carrier_name = "unknown"
        
        number_type = phonenumbers.number_type(parsed_number)
        
        logger.info("Phone validation successful", 
                    formatted_phone=formatted_phone,
                    region_code=region_code,
                    carrier=carrier_name,
                    number_type=str(number_type),
                    session_id=session_id)
        
        return {
            "phoneNumber": formatted_phone,
            "isValid": True,
            "sessionId": session_id,
            "userMessage": sms_body,
            "metadata": {
                "original": raw_phone,
                "region": region_code,
                "carrier": carrier_name,
                "type": str(number_type)
            }
        }
        
    except NumberParseException as e:
        error_msg = f"Phone parsing error: {e.error_type}"
        logger.error("Phone number parse exception", 
                     raw_phone=raw_phone,
                     error=str(e),
                     session_id=session_id)
        
        return {
            "phoneNumber": raw_phone,
            "isValid": False,
            "sessionId": session_id,
            "error": error_msg,
            "userMessage": sms_body
        }
    
    except Exception as e:
        error_msg = f"Unexpected validation error: {str(e)}"
        logger.error("Unexpected phone validation error", 
                     raw_phone=raw_phone,
                     error=str(e),
                     session_id=session_id)
        
        return {
            "phoneNumber": raw_phone,
            "isValid": False,
            "sessionId": session_id,
            "error": error_msg,
            "userMessage": sms_body
        }

def is_phone_number_mobile(phone_number: str) -> bool:
    """
    Helper function to check if phone number is mobile
    Useful for SMS delivery validation
    """
    try:
        parsed = phonenumbers.parse(phone_number, None)
        number_type = phonenumbers.number_type(parsed)
        return number_type in [
            phonenumbers.PhoneNumberType.MOBILE,
            phonenumbers.PhoneNumberType.FIXED_LINE_OR_MOBILE
        ]
    except:
        return False

# Test function for validation
if __name__ == "__main__":
    # Test cases
    test_cases = [
        {"From": "+1234567890", "Body": "Hello"},
        {"From": "(555) 123-4567", "Body": "I want to book an appointment"},
        {"From": "invalid", "Body": "Test message"},
        {"From": "+44 20 7946 0958", "Body": "UK number test"},
    ]
    
    print("Testing phone validation...")
    for i, test_case in enumerate(test_cases):
        print(f"\nTest {i+1}: {test_case}")
        result = validate_phone_number(test_case)
        print(f"Result: {result}")
        print(f"Mobile check: {is_phone_number_mobile(result['phoneNumber'])}")
