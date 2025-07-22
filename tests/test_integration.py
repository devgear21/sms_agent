"""
Integration Tests for SMS Appointment Booking Agent
Tests complete conversation flows and API integrations
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from unittest.mock import Mock, patch, AsyncMock
from fastapi.testclient import TestClient
import httpx

# Test imports
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app, orchestrator, TwilioWebhook

class TestConversationFlows:
    """Test complete conversation flows from start to finish"""
    
    def setup_method(self):
        """Set up test client"""
        self.client = TestClient(app)
    
    @patch('main.orchestrator.process_sms')
    def test_twilio_webhook_endpoint(self, mock_process):
        """Test Twilio webhook endpoint receives and processes messages"""
        
        mock_process.return_value = {"status": "processing", "session_id": "test-123"}
        
        # Simulate Twilio webhook payload
        webhook_data = {
            'MessageSid': 'SM1234567890abcdef',
            'AccountSid': 'AC1234567890abcdef',
            'From': '+12345678901',
            'To': '+19876543210',
            'Body': 'I want to book an appointment tomorrow at 2pm',
            'NumMedia': '0'
        }
        
        response = self.client.post("/webhook/twilio", data=webhook_data)
        
        assert response.status_code == 200
        assert response.text == "OK"
        
        # Verify process_sms was called
        mock_process.assert_called_once()
    
    def test_health_endpoint(self):
        """Test health check endpoint"""
        response = self.client.get("/health")
        
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "timestamp" in data
        assert data["version"] == "1.0.0"
    
    def test_metrics_endpoint(self):
        """Test metrics endpoint"""
        response = self.client.get("/metrics")
        
        assert response.status_code == 200
        data = response.json()
        assert "total_sessions" in data
        assert "completed_sessions" in data
        assert "success_rate" in data
        assert "active_sessions" in data

class TestConversationOrchestrator:
    """Test the conversation orchestrator with various scenarios"""
    
    @pytest.mark.asyncio
    @patch('nodes.phone_validator.validate_phone_number')
    @patch('nodes.twilio_sender.send_welcome_sms')
    @patch('nodes.groq_processor.process_user_message')
    @patch('nodes.calendly_checker.check_calendly_availability')
    @patch('nodes.calendly_creator.create_calendly_event')
    @patch('nodes.twilio_sender.send_confirmation_sms')
    @patch('tracing.langsmith_monitor.langsmith_monitor')
    async def test_successful_booking_flow(self, mock_langsmith, mock_confirm, 
                                         mock_create, mock_check, mock_groq, 
                                         mock_welcome, mock_validate):
        """Test successful end-to-end booking flow"""
        
        # Setup mocks
        mock_validate.return_value = {
            'isValid': True,
            'phoneNumber': '+12345678901',
            'sessionId': 'test-session-success',
            'userMessage': 'Tomorrow at 2pm'
        }
        
        mock_welcome.return_value = {'messageSent': True, 'messageId': 'welcome-123'}
        
        mock_groq.return_value = {
            'success': True,
            'extracted_datetime': '2025-01-23 14:00',
            'response_message': 'Checking availability for tomorrow at 2 PM',
            'next_state': 'checking_availability',
            'needs_more_info': False
        }
        
        mock_check.return_value = {
            'isAvailable': True,
            'exactMatch': True,
            'confirmedSlot': {
                'start_time': '2025-01-23T14:00:00',
                'end_time': '2025-01-23T14:30:00'
            }
        }
        
        mock_create.return_value = {
            'success': True,
            'eventId': 'cal-event-123',
            'eventUrl': 'https://calendly.com/event/cal-event-123',
            'confirmationDetails': {
                'event_name': 'Consultation',
                'start_time': '2:00 PM',
                'date': 'January 23, 2025'
            }
        }
        
        mock_confirm.return_value = {'messageSent': True, 'messageId': 'confirm-123'}
        
        mock_session_trace = Mock()
        mock_langsmith.create_session_trace.return_value = mock_session_trace
        mock_langsmith.trace_node_execution.return_value = Mock()
        
        # Create webhook data
        webhook_data = TwilioWebhook(
            MessageSid='SM123',
            AccountSid='AC123',
            From='+12345678901',
            To='+19876543210',
            Body='Tomorrow at 2pm'
        )
        
        # Process the SMS
        result = await orchestrator.process_sms(webhook_data)
        
        # Verify result
        assert result['status'] == 'booked'
        assert result['session_id'] == 'test-session-success'
        
        # Verify all components were called
        mock_validate.assert_called_once()
        mock_welcome.assert_called_once()
        mock_groq.assert_called_once()
        mock_check.assert_called_once()
        mock_create.assert_called_once()
        mock_confirm.assert_called_once()
        
        # Verify LangSmith tracing
        mock_langsmith.create_session_trace.assert_called_once()
        mock_langsmith.finalize_session_trace.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('nodes.phone_validator.validate_phone_number')
    @patch('nodes.error_handler.send_error_sms')
    @patch('tracing.langsmith_monitor.langsmith_monitor')
    async def test_invalid_phone_number_flow(self, mock_langsmith, mock_error, mock_validate):
        """Test flow when phone number is invalid"""
        
        mock_validate.return_value = {
            'isValid': False,
            'phoneNumber': 'invalid-number',
            'sessionId': 'test-session-invalid',
            'error': 'Invalid phone number format'
        }
        
        mock_error.return_value = {'messageSent': True, 'messageId': 'error-123'}
        
        webhook_data = TwilioWebhook(
            MessageSid='SM456',
            AccountSid='AC456',
            From='invalid-number',
            To='+19876543210',
            Body='Test message'
        )
        
        result = await orchestrator.process_sms(webhook_data)
        
        assert result['status'] == 'error'
        assert 'Invalid phone number' in result['message']
        
        mock_validate.assert_called_once()
        mock_error.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('nodes.phone_validator.validate_phone_number')
    @patch('nodes.twilio_sender.send_welcome_sms')
    @patch('nodes.groq_processor.process_user_message')
    @patch('nodes.fallback_handler.send_fallback_response')
    @patch('tracing.langsmith_monitor.langsmith_monitor')
    async def test_groq_processing_failure_flow(self, mock_langsmith, mock_fallback,
                                              mock_groq, mock_welcome, mock_validate):
        """Test flow when Groq processing fails"""
        
        mock_validate.return_value = {
            'isValid': True,
            'phoneNumber': '+12345678901',
            'sessionId': 'test-session-groq-fail',
            'userMessage': 'gibberish message'
        }
        
        mock_welcome.return_value = {'messageSent': True, 'messageId': 'welcome-456'}
        
        # Simulate Groq failure
        mock_groq.return_value = {
            'success': False,
            'error': 'LLM processing failed'
        }
        
        mock_fallback.return_value = {'messageSent': True, 'messageId': 'fallback-123'}
        
        mock_session_trace = Mock()
        mock_langsmith.create_session_trace.return_value = mock_session_trace
        mock_langsmith.trace_node_execution.return_value = Mock()
        
        webhook_data = TwilioWebhook(
            MessageSid='SM789',
            AccountSid='AC789',
            From='+12345678901',
            To='+19876543210',
            Body='gibberish message'
        )
        
        result = await orchestrator.process_sms(webhook_data)
        
        assert result['status'] == 'fallback'
        assert result['session_id'] == 'test-session-groq-fail'
        
        mock_fallback.assert_called_once()
    
    @pytest.mark.asyncio
    @patch('nodes.phone_validator.validate_phone_number')
    @patch('nodes.twilio_sender.send_welcome_sms')
    @patch('nodes.groq_processor.process_user_message')
    @patch('nodes.calendly_checker.check_calendly_availability')
    @patch('nodes.twilio_sender.send_availability_response')
    @patch('tracing.langsmith_monitor.langsmith_monitor')
    async def test_no_availability_flow(self, mock_langsmith, mock_availability_response,
                                      mock_check, mock_groq, mock_welcome, mock_validate):
        """Test flow when requested time is not available"""
        
        mock_validate.return_value = {
            'isValid': True,
            'phoneNumber': '+12345678901',
            'sessionId': 'test-session-no-avail',
            'userMessage': 'Tomorrow at 2pm'
        }
        
        mock_welcome.return_value = {'messageSent': True, 'messageId': 'welcome-789'}
        
        mock_groq.return_value = {
            'success': True,
            'extracted_datetime': '2025-01-23 14:00',
            'response_message': 'Checking availability',
            'next_state': 'checking_availability',
            'needs_more_info': False
        }
        
        mock_check.return_value = {
            'isAvailable': False,
            'exactMatch': False,
            'suggestedAlternatives': [
                'January 23, 2025 at 3:00 PM',
                'January 24, 2025 at 2:00 PM'
            ]
        }
        
        mock_session_trace = Mock()
        mock_langsmith.create_session_trace.return_value = mock_session_trace
        mock_langsmith.trace_node_execution.return_value = Mock()
        
        webhook_data = TwilioWebhook(
            MessageSid='SM101',
            AccountSid='AC101',
            From='+12345678901',
            To='+19876543210',
            Body='Tomorrow at 2pm'
        )
        
        result = await orchestrator.process_sms(webhook_data)
        
        assert result['status'] == 'processing'
        assert result['session_id'] == 'test-session-no-avail'
        
        mock_check.assert_called_once()

class TestSessionManagement:
    """Test session management and state persistence"""
    
    def test_session_creation(self):
        """Test new session creation"""
        session_id = 'test-session-new'
        phone_number = '+12345678901'
        
        session = orchestrator._get_or_create_session(session_id, phone_number)
        
        assert session['sessionId'] == session_id
        assert session['phoneNumber'] == phone_number
        assert session['conversationState'] == 'new'
        assert 'startTime' in session
        assert session['steps'] == []
        assert session['errorCount'] == 0
    
    def test_session_retrieval(self):
        """Test retrieving existing session"""
        session_id = 'test-session-existing'
        phone_number = '+12345678901'
        
        # Create session
        session1 = orchestrator._get_or_create_session(session_id, phone_number)
        session1['conversationState'] = 'collecting_preferences'
        session1['steps'].append('welcome_sent')
        
        # Retrieve same session
        session2 = orchestrator._get_or_create_session(session_id, phone_number)
        
        assert session1 is session2
        assert session2['conversationState'] == 'collecting_preferences'
        assert 'welcome_sent' in session2['steps']

class TestErrorScenarios:
    """Test various error scenarios and recovery"""
    
    @pytest.mark.asyncio
    async def test_general_exception_handling(self):
        """Test handling of unexpected exceptions"""
        
        # Create webhook data that will cause an exception
        webhook_data = TwilioWebhook(
            MessageSid='SM_ERROR',
            AccountSid='AC_ERROR',
            From='+12345678901',
            To='+19876543210',
            Body='Test error scenario'
        )
        
        # Mock validate_phone_number to raise an exception
        with patch('nodes.phone_validator.validate_phone_number') as mock_validate:
            mock_validate.side_effect = Exception("Unexpected error")
            
            with patch('nodes.error_handler.send_error_sms') as mock_error:
                mock_error.return_value = {'messageSent': True}
                
                result = await orchestrator.process_sms(webhook_data)
                
                assert result['status'] == 'error'
                assert 'Conversation processing error' in result['message']

class TestConversationRecovery:
    """Test conversation recovery and retry scenarios"""
    
    @pytest.mark.asyncio
    @patch('nodes.phone_validator.validate_phone_number')
    @patch('nodes.twilio_sender.send_welcome_sms')
    @patch('nodes.groq_processor.process_user_message')
    async def test_retry_after_unclear_message(self, mock_groq, mock_welcome, mock_validate):
        """Test conversation continues after unclear user message"""
        
        mock_validate.return_value = {
            'isValid': True,
            'phoneNumber': '+12345678901',
            'sessionId': 'test-session-retry',
            'userMessage': 'unclear message'
        }
        
        mock_welcome.return_value = {'messageSent': True, 'messageId': 'welcome-retry'}
        
        # First response - needs more info
        mock_groq.return_value = {
            'success': True,
            'extracted_datetime': None,
            'response_message': 'Could you be more specific about the time?',
            'next_state': 'collecting_preferences',
            'needs_more_info': True
        }
        
        webhook_data = TwilioWebhook(
            MessageSid='SM_RETRY',
            AccountSid='AC_RETRY',
            From='+12345678901',
            To='+19876543210',
            Body='unclear message'
        )
        
        result = await orchestrator.process_sms(webhook_data)
        
        assert result['status'] == 'processing'
        assert result['session_id'] == 'test-session-retry'

class TestPerformanceMetrics:
    """Test performance monitoring and metrics collection"""
    
    def test_conversation_timing_metrics(self):
        """Test that conversation timing is properly tracked"""
        # This would test that the orchestrator properly tracks timing
        # for LangSmith monitoring
        pass
    
    def test_error_rate_tracking(self):
        """Test error rate tracking across sessions"""
        # This would test aggregated error metrics
        pass

# Utility functions for integration tests
def create_test_webhook_data(from_number: str, message: str) -> TwilioWebhook:
    """Helper to create test webhook data"""
    return TwilioWebhook(
        MessageSid=f'SM{datetime.now().timestamp()}',
        AccountSid='AC_TEST',
        From=from_number,
        To='+19876543210',
        Body=message
    )

def assert_successful_flow(result: dict, expected_session_id: str):
    """Helper to assert successful conversation flow"""
    assert result['status'] == 'booked'
    assert result['session_id'] == expected_session_id

def assert_error_flow(result: dict, expected_error_type: str):
    """Helper to assert error flow"""
    assert result['status'] == 'error'
    assert expected_error_type in result.get('message', '')

if __name__ == "__main__":
    # Run integration tests
    pytest.main([
        __file__ + "::TestConversationFlows",
        __file__ + "::TestConversationOrchestrator", 
        __file__ + "::TestSessionManagement",
        __file__ + "::TestErrorScenarios",
        __file__ + "::TestConversationRecovery",
        "-v",
        "--asyncio-mode=auto"
    ])
