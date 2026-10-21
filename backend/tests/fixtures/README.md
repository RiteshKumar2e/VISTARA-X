Speech fixtures for `test_speech.py`. They are **synthetic speech** generated with the
Windows text-to-speech voice "Microsoft Zira Desktop" (System.Speech), not recordings
of people:

- `tts_en_storage_room.wav`: "Take the robot to the storage room."
- `tts_en_stop.wav`: "Stop."

No Hindi TTS voice was installed on the development machine, so Hindi speech
recognition is not covered by an automated test; Hindi text commands are.
