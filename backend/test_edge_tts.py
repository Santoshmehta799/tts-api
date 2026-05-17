#!/usr/bin/env python3
"""
Quick test script to check if Microsoft Edge TTS service is working.
Tests multiple voices to identify which ones are currently functional.
"""

import asyncio
import edge_tts
import tempfile
import os
import sys
from datetime import datetime

# Test configuration
TEST_TEXT = "Hello, this is a test of the Microsoft Edge TTS service."
TEST_VOICES = [
    # Problematic voices (from failure analysis)
    "en-US-AndrewMultilingualNeural",
    "en-US-AndrewNeural",
    "en-US-AnaNeural",

    # Reliable alternatives
    "en-US-GuyNeural",
    "en-US-AriaNeural",
    "en-US-JennyNeural",
]

TIMEOUT = 10  # seconds

async def test_voice(voice_name: str, text: str) -> tuple[bool, str, float]:
    """
    Test a single voice.

    Returns:
        (success, message, duration)
    """
    start_time = asyncio.get_event_loop().time()

    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
            temp_filename = tmp_file.name

        try:
            # Create communicate object
            communicate = edge_tts.Communicate(text=text, voice=voice_name)

            # Attempt to generate audio with timeout
            await asyncio.wait_for(
                communicate.save(temp_filename),
                timeout=TIMEOUT
            )

            # Check if file was created and has content
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                file_size = os.path.getsize(temp_filename)
                duration = asyncio.get_event_loop().time() - start_time
                return True, f"OK ({file_size} bytes, {duration:.2f}s)", duration
            else:
                duration = asyncio.get_event_loop().time() - start_time
                return False, f"FAILED: Empty file ({duration:.2f}s)", duration

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

    except asyncio.TimeoutError:
        duration = asyncio.get_event_loop().time() - start_time
        return False, f"TIMEOUT after {TIMEOUT}s", duration

    except edge_tts.exceptions.NoAudioReceived as e:
        duration = asyncio.get_event_loop().time() - start_time
        return False, f"NoAudioReceived ({duration:.2f}s)", duration

    except Exception as e:
        duration = asyncio.get_event_loop().time() - start_time
        return False, f"ERROR: {type(e).__name__}: {str(e)[:50]}", duration

async def test_all_voices():
    """Test all configured voices"""
    print("=" * 70)
    print("Microsoft Edge TTS Service Test")
    print("=" * 70)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Test text: \"{TEST_TEXT}\"")
    print(f"Timeout: {TIMEOUT} seconds")
    print("=" * 70)
    print()

    results = []

    for voice in TEST_VOICES:
        print(f"Testing: {voice:<35} ... ", end="", flush=True)
        success, message, duration = await test_voice(voice, TEST_TEXT)
        results.append((voice, success, message, duration))

        # Print result with color
        if success:
            print(f"✓ {message}")
        else:
            print(f"✗ {message}")

    print()
    print("=" * 70)
    print("Summary")
    print("=" * 70)

    successful = sum(1 for _, success, _, _ in results if success)
    failed = len(results) - successful

    print(f"Total voices tested: {len(results)}")
    print(f"Successful: {successful}")
    print(f"Failed: {failed}")
    print(f"Success rate: {(successful/len(results)*100):.1f}%")

    if failed > 0:
        print()
        print("Failed voices:")
        for voice, success, message, _ in results:
            if not success:
                print(f"  - {voice}: {message}")

    print("=" * 70)

    # Return exit code
    return 0 if successful > 0 else 1

async def quick_test():
    """Quick test with just one reliable voice"""
    print("Quick test with en-US-AriaNeural...")
    success, message, duration = await test_voice("en-US-AriaNeural", TEST_TEXT)

    if success:
        print(f"✓ Microsoft Edge TTS service is UP - {message}")
        return 0
    else:
        print(f"✗ Microsoft Edge TTS service is DOWN - {message}")
        return 1

def main():
    """Main entry point"""
    if len(sys.argv) > 1 and sys.argv[1] == "--quick":
        exit_code = asyncio.run(quick_test())
    else:
        exit_code = asyncio.run(test_all_voices())

    sys.exit(exit_code)

if __name__ == "__main__":
    main()
