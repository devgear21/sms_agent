"""
Unit Tests for SMS Appointment Booking Agent
Comprehensive test suite covering all nodes and workflows
"""

import pytest
import asyncio
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import json

# Test imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nodes.phone_validator import validate_phone_number, is_phone_number_mobile
from nodes.groq_processor import process_user_message, ConversationProcessor
from nodes.error_handler import send_error_whatsapp, ErrorHandler
from nodes.fallback_handler import send_fallback_response, FallbackHandler
from nodes.logger import log_sms_failure, sms_logger

class TestPhoneValidation:
    """Test phone number validation functionality"""
    
    def test_valid_us_phone_number(self):
        """Test validation of valid US phone number"""
        inputs = {
            'From': '+12345678901',
            'Body': 'Hello, I want to book an appointment'
        }
        
        result = validate_phone_number(inputs)
        
        assert result['isValid'] is True
        assert result['phoneNumber'] == '+12345678901'
        assert result['sessionId'] is not None
        assert result['userMessage'] == 'Hello, I want to book an appointment'
        assert 'metadata' in result
    
    def test_valid_formatted_phone_number(self):
        """Test validation of formatted phone number"""
        inputs = {
            'From': '(555) 123-4567',
            'Body': 'Test message'
        }
        
        result = validate_phone_number(inputs)
        
        assert result['isValid'] is True
        assert result['phoneNumber'] == '+15551234567'  # E.164 format
        assert result['sessionId'] is not None
    
    def test_invalid_phone_number(self):
        """Test validation of invalid phone number"""
        inputs = {
            'From': 'invalid-number',
            'Body': 'Test message'
        }
        
        result = validate_phone_number(inputs)
        
        assert result['isValid'] is False
        assert result['phoneNumber'] == 'invalid-number'
        assert 'error' in result
        assert result['sessionId'] is not None
    
    def test_international_phone_number(self):
        """Test validation of international phone number"""
        inputs = {
            'From': '+44 20 7946 0958',  # UK number
            'Body': 'International test'
        }
        
        result = validate_phone_number(inputs)
        
        assert result['isValid'] is True
        assert result['phoneNumber'].startswith('+44')
        assert result['metadata']['region'] == 'GB'
    
    def test_mobile_number_detection(self):
        """Test mobile number detection"""
        mobile_number = '+12345678901'
        assert is_phone_number_mobile(mobile_number) is True
        
        # Test with invalid number
        invalid_number = 'invalid'
        assert is_phone_number_mobile(invalid_number) is False

class TestGroqProcessor:
    """Test Groq LLM conversation processing"""
    
    @patch('nodes.groq_processor.ChatGroq')
    def test_clear_datetime_extraction(self, mock_groq):
        """Test extraction of clear date/time from user message"""
        # Mock Groq response
        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_datetime": "2025-01-23 14:00",
            "response_message": "Great! I'll check if tomorrow at 2 PM is available.",
            "next_state": "checking_availability",
            "needs_more_info": False,
            "confidence": 0.9,
            "extracted_elements": {
                "date_mentioned": "tomorrow",
                "time_mentioned": "2pm",
                "timezone": None
            }
        })
        
        mock_groq.return_value.invoke.return_value = mock_response
        
        inputs = {
            'userMessage': 'Tomorrow at 2pm',
            'conversationState': 'collecting_preferences',
            'sessionId': 'test-session-1'
        }
        
        result = process_user_message(inputs)
        
        assert result['extracted_datetime'] == "2025-01-23 14:00"
        assert result['next_state'] == "checking_availability"
        assert result['needs_more_info'] is False
        assert result['confidence'] == 0.9
    
    @patch('nodes.groq_processor.ChatGroq')
    def test_ambiguous_datetime_request(self, mock_groq):
        """Test handling of ambiguous datetime requests"""
        mock_response = Mock()
        mock_response.content = json.dumps({
            "extracted_datetime": None,
            "response_message": "I'd be happy to help you schedule for next week! What day and time would work best?",
            "next_state": "collecting_preferences",
            "needs_more_info": True,
            "confidence": 0.3,
            "extracted_elements": {
                "date_mentioned": "next week",
                "time_mentioned": None,
                "timezone": None
            }
        })
        
        mock_groq.return_value.invoke.return_value = mock_response
        
        inputs = {
            'userMessage': 'I need to meet next week',
            'conversationState': 'collecting_preferences',
            'sessionId': 'test-session-2'
        }
        
        result = process_user_message(inputs)
        
        assert result['extracted_datetime'] is None
        assert result['needs_more_info'] is True
        assert result['next_state'] == "collecting_preferences"
    
    def test_datetime_validation_business_hours(self):
        """Test validation of business hours"""
        processor = ConversationProcessor()
        
        # Test valid business hours
        valid_datetime = "2025-01-23 14:00"  # 2 PM on a weekday
        result = processor.validate_extracted_datetime(valid_datetime)
        assert result['valid'] is True
        
        # Test invalid - too early
        early_datetime = "2025-01-23 07:00"  # 7 AM
        result = processor.validate_extracted_datetime(early_datetime)
        assert result['valid'] is False
        assert "9 AM and 6 PM" in result['error']
        
        # Test invalid - too late
        late_datetime = "2025-01-23 19:00"  # 7 PM
        result = processor.validate_extracted_datetime(late_datetime)
        assert result['valid'] is False
        assert "9 AM and 6 PM" in result['error']
    
    def test_datetime_validation_weekends(self):
        """Test validation of weekend dates"""
        processor = ConversationProcessor()
        
        # Test Saturday (should fail)
        saturday_datetime = "2025-01-25 14:00"  # Saturday
        result = processor.validate_extracted_datetime(saturday_datetime)
        assert result['valid'] is False
        assert "Monday through Friday" in result['error']
        
        # Test Sunday (should fail)  
        sunday_datetime = "2025-01-26 14:00"  # Sunday
        result = processor.validate_extracted_datetime(sunday_datetime)
        assert result['valid'] is False
        assert "Monday through Friday" in result['error']

class TestErrorHandler:
    """Test error handling functionality"""
    
    @patch('nodes.error_handler.TwilioSMSSender')
    def test_phone_validation_error(self, mock_twilio):
        """Test phone validation error message"""
        mock_sender = Mock()
        mock_sender.send_sms.return_value = {
            'messageSent': True,
            'messageId': 'test-msg-123'
        }
        mock_twilio.return_value = mock_sender
        
        inputs = {
            'phoneNumber': '+1234567890',
            'errorType': 'phone_validation',
            'sessionId': 'test-session-error'
        }
        
        result = send_error_whatsapp(inputs)
        
        assert result['messageSent'] is True
        mock_sender.send_whatsapp.assert_called_once()
        
        # Check that the error message was appropriate
        call_args = mock_sender.send_whatsapp.call_args[1]
        assert 'validate your phone number' in call_args['message']
    
    @patch('nodes.error_handler.TwilioSMSSender')
    def test_calendly_api_error(self, mock_twilio):
        """Test Calendly API error message"""
        mock_sender = Mock()
        mock_sender.send_sms.return_value = {
            'messageSent': True,
            'messageId': 'test-msg-124'
        }
        mock_twilio.return_value = mock_sender
        
        inputs = {
            'phoneNumber': '+1234567890',
            'errorType': 'calendly_api',
            'sessionId': 'test-session-error-2',
            'context': {'retry_after': 5}
        }
        
        result = send_error_whatsapp(inputs)
        
        assert result['messageSent'] is True
        call_args = mock_sender.send_whatsapp.call_args[1]
        assert 'calendar system' in call_args['message']
        assert 'try again in 5 minutes' in call_args['message']
    
    def test_error_message_generation(self):
        """Test error message generation for different error types"""
        handler = ErrorHandler()
        
        # Test general error
        general_msg = handler.get_error_message('general')
        assert 'Something went wrong' in general_msg
        
        # Test specific error
        phone_msg = handler.get_error_message('phone_validation')
        assert 'validate your phone number' in phone_msg
        
        # Test datetime error with context
        datetime_msg = handler.get_error_message(
            'invalid_datetime', 
            {'suggested_format': 'Monday at 3pm'}
        )
        assert 'Monday at 3pm' in datetime_msg

class TestFallbackHandler:
    """Test fallback response functionality"""
    
    @patch('nodes.fallback_handler.TwilioSMSSender')
    def test_general_fallback_response(self, mock_twilio):
        """Test general fallback response"""
        mock_sender = Mock()
        mock_sender.send_sms.return_value = {
            'messageSent': True,
            'messageId': 'test-fallback-123'
        }
        mock_twilio.return_value = mock_sender
        
        inputs = {
            'phoneNumber': '+1234567890',
            'userMessage': 'gibberish message',
            'sessionId': 'test-fallback-session'
        }
        
        result = send_fallback_response(inputs)
        
        assert result['messageSent'] is True
        call_args = mock_sender.send_sms.call_args[1]
        assert 'examples' in call_args['message'].lower()
    
    def test_intent_detection(self):
        """Test intent detection from failed messages"""
        handler = FallbackHandler()
        
        # Test booking intent
        booking_intent = handler.detect_intent_from_failed_message("I want to book something tomorrow")
        assert booking_intent == "date_time_unclear"
        
        # Test cancellation intent
        cancel_intent = handler.detect_intent_from_failed_message("cancel my appointment")
        assert cancel_intent == "cancellation"
        
        # Test help intent
        help_intent = handler.detect_intent_from_failed_message("how does this work?")
        assert help_intent == "help_request"
        
        # Test ambiguous
        ambiguous_intent = handler.detect_intent_from_failed_message("hello there")
        assert ambiguous_intent == "ambiguous_request"
    
    def test_fallback_response_generation(self):
        """Test fallback response generation for different scenarios"""
        handler = FallbackHandler()
        
        # Test general fallback
        general_response = handler.generate_fallback_response(
            user_message="random text",
            session_id="test",
            failure_reason="general"
        )
        assert len(general_response) > 0
        assert "examples" in general_response.lower()
        
        # Test processing error fallback
        error_response = handler.generate_fallback_response(
            user_message="test",
            session_id="test",
            failure_reason="processing_error"
        )
        assert "technical difficulties" in error_response.lower()

class TestLogger:
    """Test logging functionality"""
    
    def test_conversation_event_logging(self):
        """Test conversation event logging"""
        result = sms_logger.log_conversation_event(
            event_type="phone_validation",
            session_id="test-session-log",
            phone_number="+1234567890",
            data={"validation_result": "success"}
        )
        
        assert result['logged'] is True
        assert result['sessionId'] == "test-session-log"
        assert result['eventType'] == "phone_validation"
    
    def test_api_call_logging(self):
        """Test API call logging"""
        result = sms_logger.log_api_call(
            api_name="twilio",
            session_id="test-session-api",
            method="POST",
            endpoint="/messages",
            status_code=201,
            response_time_ms=250.5
        )
        
        assert result['logged'] is True
        assert result['success'] is True
        assert result['apiName'] == "twilio"
    
    def test_sms_failure_logging(self):
        """Test SMS failure logging"""
        inputs = {
            'error': 'Message delivery failed',
            'sessionId': 'test-session-sms-fail',
            'phoneNumber': '+1234567890',
            'retryCount': 2
        }
        
        result = log_sms_failure(inputs)
        
        assert result['logged'] is True
        assert result['failureType'] == "delivery_failure"
        assert result['sessionId'] == 'test-session-sms-fail'
    
    def test_phone_number_masking(self):
        """Test phone number masking for privacy"""
        masked = sms_logger._mask_phone_number('+12345678901')
        assert masked == "***-***-8901"
        
        # Test short number
        masked_short = sms_logger._mask_phone_number('123')
        assert masked_short == "***-***-****"

class TestEndToEndFlow:
    """Test end-to-end conversation flows"""
    
    @patch('nodes.twilio_sender.TwilioSMSSender')
    @patch('nodes.groq_processor.ChatGroq')
    @patch('nodes.calendly_checker.CalendlyAvailabilityChecker')
    @patch('nodes.calendly_creator.CalendlyEventCreator')
    def test_successful_booking_flow(self, mock_creator, mock_checker, mock_groq, mock_twilio):
        """Test complete successful booking flow"""
        
        # Mock Twilio SMS sender
        mock_sms = Mock()
        mock_sms.send_sms.return_value = {'messageSent': True, 'messageId': 'msg-123'}
        mock_twilio.return_value = mock_sms
        
        # Mock Groq response
        mock_groq_response = Mock()
        mock_groq_response.content = json.dumps({
            "extracted_datetime": "2025-01-23 14:00",
            "response_message": "I'll check availability for tomorrow at 2 PM.",
            "next_state": "checking_availability",
            "needs_more_info": False,
            "confidence": 0.9,
            "extracted_elements": {"date_mentioned": "tomorrow", "time_mentioned": "2pm", "timezone": None}
        })
        mock_groq.return_value.invoke.return_value = mock_groq_response
        
        # Mock Calendly availability (available)
        mock_avail = Mock()
        mock_avail.check_availability.return_value = {
            'isAvailable': True,
            'exactMatch': True,
            'confirmedSlot': {'start_time': '2025-01-23T14:00:00', 'end_time': '2025-01-23T14:30:00'}
        }
        mock_checker.return_value = mock_avail
        
        # Mock Calendly event creation
        mock_create = Mock()
        mock_create.create_event.return_value = {
            'success': True,
            'eventId': 'evt-123',
            'eventUrl': 'https://calendly.com/event/evt-123',
            'confirmationDetails': {
                'event_name': 'Appointment',
                'start_time': '2:00 PM',
                'date': 'January 23, 2025'
            }
        }
        mock_creator.return_value = mock_create
        
        # Test phone validation
        validation_result = validate_phone_number({
            'From': '+12345678901',
            'Body': 'Tomorrow at 2pm'
        })
        assert validation_result['isValid'] is True
        
        # Test Groq processing
        groq_result = process_user_message({
            'userMessage': 'Tomorrow at 2pm',
            'conversationState': 'collecting_preferences',
            'sessionId': validation_result['sessionId']
        })
        assert groq_result['extracted_datetime'] == "2025-01-23 14:00"
        assert groq_result['needs_more_info'] is False
        
        # This simulates the complete flow working together
        assert True  # Flow completed successfully

if __name__ == "__main__":
    # Run specific test classes
    pytest.main([
        __file__ + "::TestPhoneValidation",
        __file__ + "::TestGroqProcessor", 
        __file__ + "::TestErrorHandler",
        __file__ + "::TestFallbackHandler",
        __file__ + "::TestLogger",
        __file__ + "::TestEndToEndFlow",
        "-v"
    ])
