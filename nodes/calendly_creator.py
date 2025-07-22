"""
Calendly Event Creator Node
Creates appointments in Calendly and handles booking confirmations
"""

import os
import requests
from datetime import datetime
from typing import Dict, Any, Optional
from langsmith import traceable
import structlog
import json

# Configure structured logging
logger = structlog.get_logger()

class CalendlyEventCreator:
    def __init__(self):
        """Initialize Calendly API client for event creation"""
        self.api_token = os.getenv('CALENDLY_API_TOKEN')
        self.user_uri = os.getenv('CALENDLY_USER_URI')
        
        if not self.api_token or not self.user_uri:
            raise ValueError("CALENDLY_API_TOKEN and CALENDLY_USER_URI environment variables are required")
        
        self.base_url = "https://api.calendly.com"
        self.headers = {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json"
        }
        
        logger.info("Calendly event creator initialized", user_uri=self.user_uri)

    @traceable(
        name="create_calendly_event",
        tags=["calendly", "booking", "creation", "api"],
        metadata={"component": "calendly_creator"}
    )
    def create_event(self, requested_datetime: str, phone_number: str, 
                    session_id: str, event_type_uri: str = None,
                    invitee_name: str = None, invitee_email: str = None) -> Dict[str, Any]:
        """
        Create an appointment event in Calendly
        
        Args:
            requested_datetime: ISO format datetime string
            phone_number: Invitee's phone number
            session_id: Session identifier
            event_type_uri: Specific event type URI (if available)
            invitee_name: Invitee's name (optional)
            invitee_email: Invitee's email (optional, will be derived from phone if not provided)
        
        Returns:
            Dict with event creation results
        """
        
        logger.info("Creating Calendly event", 
                    requested_datetime=requested_datetime,
                    phone_number=phone_number,
                    session_id=session_id)
        
        try:
            # Parse requested datetime
            requested_dt = datetime.fromisoformat(requested_datetime.replace('Z', '+00:00'))
            
            # Get event type if not provided
            if not event_type_uri:
                event_types = self._get_event_types()
                if not event_types:
                    return {
                        "success": False,
                        "error": "No event types available",
                        "sessionId": session_id
                    }
                event_type_uri = event_types[0]['uri']
            
            # Prepare invitee information
            if not invitee_email:
                # Generate email from phone number for Calendly
                invitee_email = f"sms-{phone_number.replace('+', '').replace('-', '')}@sms-booking.temp"
            
            if not invitee_name:
                invitee_name = f"SMS User {phone_number[-4:]}"  # Last 4 digits
            
            # Create the event scheduling request
            scheduling_data = {
                "event_type": event_type_uri,
                "start_time": requested_dt.isoformat(),
                "invitee": {
                    "email": invitee_email,
                    "name": invitee_name
                },
                "responses": {
                    "phone_number": phone_number
                }
            }
            
            # Make the API call to create the event
            response = self._schedule_event(scheduling_data)
            
            if response.get('success'):
                event_data = response['event_data']
                
                # Extract event details
                event_id = event_data.get('uri', '').split('/')[-1]
                event_url = event_data.get('uri', '')
                start_time = event_data.get('start_time', '')
                end_time = event_data.get('end_time', '')
                
                # Format confirmation details
                confirmation_details = {
                    "event_id": event_id,
                    "event_name": event_data.get('name', 'Appointment'),
                    "start_time": self._format_datetime(start_time),
                    "end_time": self._format_datetime(end_time),
                    "date": self._format_date(start_time),
                    "invitee_name": invitee_name,
                    "invitee_email": invitee_email,
                    "phone_number": phone_number
                }
                
                logger.info("Calendly event created successfully", 
                           event_id=event_id,
                           start_time=start_time,
                           session_id=session_id)
                
                return {
                    "success": True,
                    "eventId": event_id,
                    "eventUrl": event_url,
                    "confirmationDetails": confirmation_details,
                    "sessionId": session_id,
                    "createdAt": datetime.utcnow().isoformat()
                }
            
            else:
                error_msg = response.get('error', 'Unknown error during event creation')
                logger.error("Failed to create Calendly event", 
                           error=error_msg,
                           session_id=session_id)
                
                return {
                    "success": False,
                    "error": error_msg,
                    "sessionId": session_id
                }
        
        except Exception as e:
            error_msg = f"Event creation failed: {str(e)}"
            logger.error("Calendly event creation exception", 
                        error=str(e),
                        requested_datetime=requested_datetime,
                        session_id=session_id)
            
            return {
                "success": False,
                "error": error_msg,
                "sessionId": session_id
            }

    def _get_event_types(self) -> list:
        """Get available event types for the user"""
        try:
            url = f"{self.base_url}/event_types"
            params = {"user": self.user_uri}
            
            response = requests.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            
            data = response.json()
            return data.get('collection', [])
            
        except Exception as e:
            logger.error("Failed to get event types", error=str(e))
            return []

    def _schedule_event(self, scheduling_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Make the actual API call to schedule the event
        Note: Calendly API v2 uses a different approach for scheduling
        """
        try:
            # For demonstration, we'll simulate the scheduling
            # In production, you'd use Calendly's scheduling workflow
            
            # Calendly typically requires invitees to book through their interface
            # For SMS booking, you might need to use Calendly's Admin API or 
            # implement a custom booking flow
            
            url = f"{self.base_url}/scheduled_events"
            
            # This is a simplified approach - actual implementation would depend
            # on your Calendly plan and API access level
            response = requests.post(url, headers=self.headers, json=scheduling_data)
            
            if response.status_code == 201:
                return {
                    "success": True,
                    "event_data": response.json().get('resource', {})
                }
            else:
                return {
                    "success": False,
                    "error": f"API error: {response.status_code} - {response.text}"
                }
                
        except Exception as e:
            return {
                "success": False,
                "error": f"Scheduling request failed: {str(e)}"
            }

    def _format_datetime(self, iso_datetime: str) -> str:
        """Format ISO datetime for display"""
        try:
            dt = datetime.fromisoformat(iso_datetime.replace('Z', '+00:00'))
            return dt.strftime("%I:%M %p")
        except:
            return iso_datetime

    def _format_date(self, iso_datetime: str) -> str:
        """Format ISO datetime to date string"""
        try:
            dt = datetime.fromisoformat(iso_datetime.replace('Z', '+00:00'))
            return dt.strftime("%A, %B %d, %Y")
        except:
            return iso_datetime

    @traceable(
        name="cancel_calendly_event",
        tags=["calendly", "cancellation", "api"],
        metadata={"component": "calendly_cancellation"}
    )
    def cancel_event(self, event_id: str, session_id: str, 
                    reason: str = "Cancelled via SMS") -> Dict[str, Any]:
        """
        Cancel a Calendly event
        
        Args:
            event_id: Calendly event ID
            session_id: Session identifier
            reason: Cancellation reason
        
        Returns:
            Dict with cancellation results
        """
        
        logger.info("Cancelling Calendly event", 
                    event_id=event_id,
                    session_id=session_id,
                    reason=reason)
        
        try:
            url = f"{self.base_url}/scheduled_events/{event_id}/cancellation"
            
            cancellation_data = {
                "reason": reason
            }
            
            response = requests.post(url, headers=self.headers, json=cancellation_data)
            
            if response.status_code in [200, 201, 204]:
                logger.info("Event cancelled successfully", 
                           event_id=event_id,
                           session_id=session_id)
                
                return {
                    "success": True,
                    "eventId": event_id,
                    "message": "Event cancelled successfully",
                    "sessionId": session_id
                }
            else:
                error_msg = f"Cancellation failed: {response.status_code} - {response.text}"
                logger.error("Event cancellation failed", 
                           error=error_msg,
                           event_id=event_id,
                           session_id=session_id)
                
                return {
                    "success": False,
                    "error": error_msg,
                    "sessionId": session_id
                }
        
        except Exception as e:
            error_msg = f"Cancellation error: {str(e)}"
            logger.error("Event cancellation exception", 
                        error=str(e),
                        event_id=event_id,
                        session_id=session_id)
            
            return {
                "success": False,
                "error": error_msg,
                "sessionId": session_id
            }

# Global creator instance
event_creator = CalendlyEventCreator()

@traceable(
    name="create_calendly_event",
    tags=["calendly", "booking", "appointment"],
    metadata={"component": "event_creation"}
)
def create_calendly_event(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for creating Calendly events
    
    Args:
        inputs: Dict containing requestedDateTime, phoneNumber, sessionId
    
    Returns:
        Dict with event creation results
    """
    
    requested_datetime = inputs.get('requestedDateTime')
    phone_number = inputs.get('phoneNumber')
    session_id = inputs.get('sessionId', '')
    event_type_uri = inputs.get('eventTypeUri')
    invitee_name = inputs.get('inviteeName')
    invitee_email = inputs.get('inviteeEmail')
    
    if not requested_datetime or not phone_number:
        return {
            "success": False,
            "error": "Missing required fields: requestedDateTime and phoneNumber",
            "sessionId": session_id
        }
    
    return event_creator.create_event(
        requested_datetime=requested_datetime,
        phone_number=phone_number,
        session_id=session_id,
        event_type_uri=event_type_uri,
        invitee_name=invitee_name,
        invitee_email=invitee_email
    )

@traceable(
    name="cancel_calendly_event",
    tags=["calendly", "cancellation"],
    metadata={"component": "event_cancellation"}
)
def cancel_calendly_event(inputs: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main entry point for cancelling Calendly events
    
    Args:
        inputs: Dict containing eventId, sessionId, reason
    
    Returns:
        Dict with cancellation results
    """
    
    event_id = inputs.get('eventId')
    session_id = inputs.get('sessionId', '')
    reason = inputs.get('reason', 'Cancelled via SMS')
    
    if not event_id:
        return {
            "success": False,
            "error": "Missing required field: eventId",
            "sessionId": session_id
        }
    
    return event_creator.cancel_event(
        event_id=event_id,
        session_id=session_id,
        reason=reason
    )

# Test function
if __name__ == "__main__":
    from datetime import timedelta
    
    # Test event creation
    test_datetime = (datetime.now() + timedelta(days=1)).replace(hour=14, minute=0, second=0, microsecond=0)
    
    print("Testing Calendly event creation...")
    print(f"Creating event for: {test_datetime.isoformat()}")
    
    result = create_calendly_event({
        "requestedDateTime": test_datetime.isoformat(),
        "phoneNumber": "+1234567890",
        "sessionId": "test-session-creation",
        "inviteeName": "Test User",
        "inviteeEmail": "test@example.com"
    })
    
    print(f"Creation result: {result}")
    
    # Test cancellation if event was created
    if result.get('success') and result.get('eventId'):
        print("\nTesting event cancellation...")
        cancel_result = cancel_calendly_event({
            "eventId": result['eventId'],
            "sessionId": "test-session-creation",
            "reason": "Test cancellation"
        })
        print(f"Cancellation result: {cancel_result}")
