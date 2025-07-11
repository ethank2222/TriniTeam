#!/usr/bin/env python3
"""
Simple test script to verify API calls are working
"""

import os
import asyncio
import aiohttp
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

async def test_api_call():
    """Test the Anthropic API call"""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("❌ ANTHROPIC_API_KEY not found in environment variables")
        return False
    
    if not api_key.startswith('sk-ant-'):
        print("❌ ANTHROPIC_API_KEY appears to be invalid (should start with 'sk-ant-')")
        return False
    
    print(f"✅ API key found: {api_key[:10]}...")
    
    # Test API call
    url = "https://api.anthropic.com/v1/messages"
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01"
    }
    
    payload = {
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 100,
        "temperature": 0.7,
        "system": "You are a helpful assistant.",
        "messages": [{"role": "user", "content": "Say 'Hello, API test successful!'"}]
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url, headers=headers, json=payload) as response:
                if response.status == 200:
                    result = await response.json()
                    response_text = result['content'][0]['text']
                    print(f"✅ API call successful!")
                    print(f"📝 Response: {response_text}")
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ API call failed: {response.status} - {error_text}")
                    return False
    except Exception as e:
        print(f"❌ Error making API call: {e}")
        return False

if __name__ == "__main__":
    print("🧪 Testing Anthropic API connection...")
    success = asyncio.run(test_api_call())
    if success:
        print("🎉 API test passed! The system should be able to make API calls.")
    else:
        print("💥 API test failed! Check your API key and network connection.") 