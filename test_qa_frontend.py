#!/usr/bin/env python
"""Test QA frontend and check for errors"""
import os
os.chdir('/mnt/d/script/agent/literature_agent-V2-claude/Cryoagent')

from playwright.sync_api import sync_playwright
import json

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Capture console messages
        console_logs = []
        page.on("console", lambda msg: console_logs.append(f"{msg.type}: {msg.text}"))

        # Capture network requests
        failed_requests = []
        page.on("requestfailed", lambda req: failed_requests.append(f"{req.url} - {req.failure.error_text}"))

        print("Navigating to http://localhost:5000/qa...")
        page.goto('http://localhost:5000/qa', wait_until='networkidle', timeout=30000)

        print("Page loaded. Taking screenshot...")
        page.screenshot(path='/tmp/qa_page.png', full_page=True)

        # Find and fill the input
        print("Looking for input field...")
        input_field = page.locator('textarea').first
        if input_field.is_visible():
            print("Found textarea, filling with 'hello'...")
            input_field.fill("hello")

            # Find and click send button
            print("Looking for send button...")
            send_button = page.locator('button:has-text("发送")').first
            if send_button.is_visible():
                print("Clicking send button...")
                send_button.click()

                # Wait for response
                print("Waiting for response...")
                page.wait_for_timeout(5000)

                # Take screenshot after
                page.screenshot(path='/tmp/qa_page_after.png', full_page=True)

                # Check for messages
                messages = page.locator('.message').all()
                print(f"Found {len(messages)} messages")

        print("\n=== Console Logs ===")
        for log in console_logs:
            print(log)

        print("\n=== Failed Requests ===")
        for req in failed_requests:
            print(req)

        # Get page content for debugging
        print("\n=== Page Title ===")
        print(page.title())

        browser.close()
        print("\nDone!")

if __name__ == '__main__':
    main()
