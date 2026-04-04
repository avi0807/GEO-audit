from google import genai

# 🔥 HARD CODE KEY HERE (temporary)
client = genai.Client(api_key="AIzaSyAltpgkw_uPa0_oYVtx4BZwu34--78-nxE")

print("Client created")

try:
    models = list(client.models.list())

    print("Models fetched:", models)

    print("\nNames:\n")
    for m in models:
        print(m.name)

except Exception as e:
    print("ERROR:", e)
