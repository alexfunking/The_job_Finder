import sys
import os

# Add root folder to path so it can import main
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import main

sys.stdout.reconfigure(line_buffering=True, encoding='utf-8')
sys.stderr.reconfigure(line_buffering=True, encoding='utf-8')

print("Starting custom test run...")
try:
    print("Running job hunt cycle...")
    main.frequent_job_hunt_cycle()
except Exception as e:
    print(f"Exception caught: {e}")
print("Test run completed.")
