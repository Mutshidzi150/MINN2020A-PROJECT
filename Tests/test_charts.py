from app import app

with app.test_client() as client:
    # Set session values to simulate logged-in Researcher with charts permission
    with client.session_transaction() as sess:
        sess['user'] = 'admin01'
        sess['role'] = 'Administrator'
    resp = client.get('/interactive_charts')
    print('Status code:', resp.status_code)
    data = resp.get_data(as_text=True)
    print('Length of response:', len(data))
    print('Contains plotly CDN:', 'plotly' in data.lower())
    # Print a short snippet around the first chart div
    idx = data.lower().find('<div id="')
    if idx != -1:
        print(data[idx:idx+200])
    else:
        # fallback: show first 300 chars
        print(data[:300])
