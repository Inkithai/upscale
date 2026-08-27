def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert "model" in body


def test_config(client):
    res = client.get("/api/config")
    assert res.status_code == 200
    body = res.json()
    assert body["upscale_factor"] == 4
    assert "JPG" in body["supported"]
    assert body["transparency_bg"] == "#FFFFFF"


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "AI Image Upscaler" in res.text
    assert "Supported: JPG, PNG, WebP, ZIP" in res.text
