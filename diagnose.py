import json
import os
import datetime
import warnings

warnings.filterwarnings("ignore")

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/fitness.heart_rate.read",
    "https://www.googleapis.com/auth/fitness.activity.read",
    "https://www.googleapis.com/auth/fitness.body.read",
]

token_path = os.path.join(os.path.dirname(__file__), "token.json")
creds = Credentials.from_authorized_user_file(token_path, SCOPES)
service = build("fitness", "v1", credentials=creds)

print("Listing all data sources...")
ds_list = service.users().dataSources().list(userId="me").execute()
data_sources = ds_list.get("dataSource", [])
print(f"Total data sources: {len(data_sources)}")

hr_sources = []
for ds in data_sources:
    dtype = ds.get("dataType", {}).get("name")
    stream_id = ds.get("dataStreamId")
    app = ds.get("application", {}).get("name")
    print(f"Type: {dtype} | App: {app} | Stream: {stream_id}")
    if dtype == "com.google.heart_rate.bpm":
        hr_sources.append(ds)

print("\n--- Heart Rate Sources ---")
print(f"Found {len(hr_sources)} heart rate sources.")

# Let's check for any data in the last 7 days!
now = datetime.datetime.now()
start_7d = now - datetime.timedelta(days=7)
start_ms = int(start_7d.timestamp() * 1000)
end_ms = int(now.timestamp() * 1000)

print(f"\nChecking aggregate heart rate from {start_7d} to {now}...")
body = {
    "aggregateBy": [{"dataTypeName": "com.google.heart_rate.bpm"}],
    "bucketByTime": {"durationMillis": 3600000},  # 1 hour buckets
    "startTimeMillis": start_ms,
    "endTimeMillis": end_ms
}
try:
    res = service.users().dataset().aggregate(userId="me", body=body).execute()
    buckets_with_data = 0
    for b in res.get("bucket", []):
        for ds in b.get("dataset", []):
            pts = ds.get("point", [])
            if pts:
                buckets_with_data += 1
                b_time = datetime.datetime.fromtimestamp(int(b["startTimeMillis"])/1000)
                print(f"Data found at {b_time}: {len(pts)} points, first val: {pts[0].get('value')}")
    if buckets_with_data == 0:
        print("No aggregate heart rate points found in the last 7 days.")
except Exception as e:
    print(f"Aggregate query failed: {e}")

# Check individual datasets for each hr data source
for ds in hr_sources:
    stream_id = ds["dataStreamId"]
    print(f"\nChecking dataset for stream: {stream_id}")
    start_ns = int(start_7d.timestamp() * 1e9)
    end_ns = int(now.timestamp() * 1e9)
    dataset_id = f"{start_ns}-{end_ns}"
    try:
        data = service.users().dataSources().datasets().get(
            userId="me", dataSourceId=stream_id, datasetId=dataset_id
        ).execute()
        pts = data.get("point", [])
        print(f"Points in last 7 days: {len(pts)}")
        if pts:
            first_t = datetime.datetime.fromtimestamp(int(pts[0]["startTimeNanos"])/1e9)
            last_t = datetime.datetime.fromtimestamp(int(pts[-1]["startTimeNanos"])/1e9)
            print(f"  First point: {first_t}, Last point: {last_t}")
            print(f"  Latest BPM: {pts[-1].get('value')}")
    except Exception as e:
        print(f"Failed to fetch dataset for {stream_id}: {e}")
