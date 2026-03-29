import requests
import time

url = "http://localhost:8001/api/chat"
session_id = "test_lead_session_" + str(int(time.time()))

def send_msg(text):
    print(f"\nUser: {text}")
    res = requests.post(url, json={"text": text, "session_id": session_id})
    print(f"AI: {res.json()['reply']}")
    time.sleep(1)

send_msg("hola")
send_msg("Quiero información sobre sus servicios dentales")
send_msg("Me llamo Carlos Santana")
send_msg("Mi número es 55 1234 5678")

print("\n--- TEST COMPLETE ---")
