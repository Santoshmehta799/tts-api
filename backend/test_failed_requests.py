#!/usr/bin/env python3
"""
Test all previously failed requests to determine if failures are due to:
1. Microsoft blocking/rate limiting (transient)
2. Invalid voice/text combinations (permanent)
"""

import asyncio
import edge_tts
import os
import tempfile
import re
from pathlib import Path
from datetime import datetime
from collections import defaultdict

REQUEST_DIR = "request_files"
TIMEOUT = 15  # seconds per request
MAX_CONCURRENT = 5  # Test 5 at a time to avoid overwhelming Microsoft

class TestResult:
    def __init__(self, job_id, voice, text_length, success, error_type, message, duration):
        self.job_id = job_id
        self.voice = voice
        self.text_length = text_length
        self.success = success
        self.error_type = error_type
        self.message = message
        self.duration = duration

def parse_request_file(filepath):
    """Parse a failed request file and extract parameters"""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    # Extract fields
    job_id_match = re.search(r'Job ID: (.+)', content)
    voice_match = re.search(r'Voice used: (.+)', content)
    params_match = re.search(r'Parameters - rate=(.+?), pitch=(.+?), volume=(.+)', content)
    text_match = re.search(r'Complete text:\n(.+)', content, re.DOTALL)

    if not all([job_id_match, voice_match, params_match, text_match]):
        return None

    job_id = job_id_match.group(1).strip()
    voice = voice_match.group(1).strip()
    rate = params_match.group(1).strip()
    pitch = params_match.group(2).strip()
    volume = params_match.group(3).strip()
    text = text_match.group(1).strip()

    # Convert parameters to edge-tts format
    speed = float(rate)
    speed_percentage = int((speed - 1) * 100)
    rate_value = f"+{speed_percentage}%" if speed_percentage >= 0 else f"{speed_percentage}%"

    pitch_value = f"+0Hz" if pitch == "0" else f"{pitch}Hz"
    if not pitch_value.startswith("+") and not pitch_value.startswith("-"):
        pitch_value = f"+{pitch_value}"

    volume_percentage = int(float(volume)) - 100
    volume_value = f"+{volume_percentage}%" if volume_percentage >= 0 else f"{volume_percentage}%"

    return {
        'job_id': job_id,
        'voice': voice,
        'text': text,
        'rate': rate_value,
        'pitch': pitch_value,
        'volume': volume_value
    }

async def test_request(params):
    """Test a single request"""
    start_time = asyncio.get_event_loop().time()

    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(suffix='.mp3', delete=False) as tmp_file:
            temp_filename = tmp_file.name

        try:
            # Create communicate object
            communicate = edge_tts.Communicate(
                text=params['text'],
                voice=params['voice'],
                rate=params['rate'],
                volume=params['volume'],
                pitch=params['pitch']
            )

            # Attempt to generate audio with timeout
            await asyncio.wait_for(
                communicate.save(temp_filename),
                timeout=TIMEOUT
            )

            # Check if file was created and has content
            if os.path.exists(temp_filename) and os.path.getsize(temp_filename) > 0:
                file_size = os.path.getsize(temp_filename)
                duration = asyncio.get_event_loop().time() - start_time
                return TestResult(
                    params['job_id'],
                    params['voice'],
                    len(params['text']),
                    True,
                    None,
                    f"Success ({file_size} bytes)",
                    duration
                )
            else:
                duration = asyncio.get_event_loop().time() - start_time
                return TestResult(
                    params['job_id'],
                    params['voice'],
                    len(params['text']),
                    False,
                    "EmptyFile",
                    "File created but empty",
                    duration
                )

        finally:
            # Clean up temp file
            if os.path.exists(temp_filename):
                os.remove(temp_filename)

    except asyncio.TimeoutError:
        duration = asyncio.get_event_loop().time() - start_time
        return TestResult(
            params['job_id'],
            params['voice'],
            len(params['text']),
            False,
            "Timeout",
            f"Timeout after {TIMEOUT}s",
            duration
        )

    except edge_tts.exceptions.NoAudioReceived as e:
        duration = asyncio.get_event_loop().time() - start_time
        return TestResult(
            params['job_id'],
            params['voice'],
            len(params['text']),
            False,
            "NoAudioReceived",
            "Microsoft rejected request",
            duration
        )

    except edge_tts.exceptions.WebSocketError as e:
        duration = asyncio.get_event_loop().time() - start_time
        return TestResult(
            params['job_id'],
            params['voice'],
            len(params['text']),
            False,
            "WebSocketError",
            str(e)[:100],
            duration
        )

    except Exception as e:
        duration = asyncio.get_event_loop().time() - start_time
        return TestResult(
            params['job_id'],
            params['voice'],
            len(params['text']),
            False,
            type(e).__name__,
            str(e)[:100],
            duration
        )

async def test_batch(request_params_list):
    """Test a batch of requests concurrently"""
    semaphore = asyncio.Semaphore(MAX_CONCURRENT)

    async def test_with_semaphore(params):
        async with semaphore:
            return await test_request(params)

    tasks = [test_with_semaphore(params) for params in request_params_list]
    return await asyncio.gather(*tasks)

async def main():
    """Main test function"""
    print("=" * 80)
    print("Testing Previously Failed Requests")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"Request directory: {REQUEST_DIR}")
    print(f"Concurrent tests: {MAX_CONCURRENT}")
    print(f"Timeout per test: {TIMEOUT}s")
    print("=" * 80)
    print()

    # Load all request files
    request_files = list(Path(REQUEST_DIR).glob("*.txt"))
    print(f"Found {len(request_files)} failed request files")
    print()

    # Parse all request files
    print("Parsing request files...")
    request_params_list = []
    parse_errors = 0

    for filepath in request_files:
        params = parse_request_file(filepath)
        if params:
            request_params_list.append(params)
        else:
            parse_errors += 1

    print(f"Successfully parsed: {len(request_params_list)}")
    print(f"Parse errors: {parse_errors}")
    print()

    if not request_params_list:
        print("No valid requests to test!")
        return

    # Test all requests
    print(f"Testing {len(request_params_list)} requests...")
    print("This may take several minutes...")
    print()

    results = await test_batch(request_params_list)

    # Analyze results
    print()
    print("=" * 80)
    print("Results Summary")
    print("=" * 80)
    print()

    successful = sum(1 for r in results if r.success)
    failed = len(results) - successful

    print(f"Total tested: {len(results)}")
    print(f"Successful: {successful} ({successful/len(results)*100:.1f}%)")
    print(f"Failed: {failed} ({failed/len(results)*100:.1f}%)")
    print()

    # Categorize failures
    if failed > 0:
        failure_types = defaultdict(list)
        for r in results:
            if not r.success:
                failure_types[r.error_type].append(r)

        print("Failure Breakdown:")
        print("-" * 80)
        for error_type, failures in sorted(failure_types.items(), key=lambda x: len(x[1]), reverse=True):
            count = len(failures)
            percentage = count / failed * 100
            print(f"  {error_type}: {count} ({percentage:.1f}% of failures)")
        print()

        # Voice-specific analysis
        voice_stats = defaultdict(lambda: {'success': 0, 'fail': 0})
        for r in results:
            if r.success:
                voice_stats[r.voice]['success'] += 1
            else:
                voice_stats[r.voice]['fail'] += 1

        print("Voice-Specific Results:")
        print("-" * 80)
        print(f"{'Voice':<40} {'Success':<10} {'Failed':<10} {'Fail %':<10}")
        print("-" * 80)

        for voice, stats in sorted(voice_stats.items(), key=lambda x: x[1]['fail'], reverse=True):
            total = stats['success'] + stats['fail']
            fail_pct = stats['fail'] / total * 100 if total > 0 else 0
            print(f"{voice:<40} {stats['success']:<10} {stats['fail']:<10} {fail_pct:<10.1f}%")
        print()

        # Show some NoAudioReceived examples
        no_audio_failures = [r for r in results if r.error_type == "NoAudioReceived"]
        if no_audio_failures:
            print(f"NoAudioReceived Examples (showing first 10 of {len(no_audio_failures)}):")
            print("-" * 80)
            for r in no_audio_failures[:10]:
                print(f"  Voice: {r.voice}")
                print(f"  Job ID: {r.job_id}")
                print(f"  Text length: {r.text_length}")
                print()

    # Show successful retests
    if successful > 0:
        print(f"Requests that NOW SUCCEED (were transient failures):")
        print("-" * 80)

        success_by_voice = defaultdict(int)
        for r in results:
            if r.success:
                success_by_voice[r.voice] += 1

        for voice, count in sorted(success_by_voice.items(), key=lambda x: x[1], reverse=True):
            print(f"  {voice}: {count} successful retests")
        print()

    print("=" * 80)
    print("Analysis:")
    print("=" * 80)

    if successful > 0:
        print(f"✓ {successful} requests now succeed - these were TRANSIENT failures")
        print("  (Microsoft rate limiting, temporary service issues)")

    no_audio_count = sum(1 for r in results if r.error_type == "NoAudioReceived")
    if no_audio_count > 0:
        print(f"✗ {no_audio_count} requests still get NoAudioReceived - likely INVALID combinations")
        print("  (Voice/language mismatch, unsupported voice, text issues)")

    print("=" * 80)

if __name__ == "__main__":
    asyncio.run(main())
