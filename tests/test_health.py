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
    assert body["upscale_factors"] == [2, 4, 8]
    assert 4 in body["output_size_presets_mb"]
    assert "JPG" in body["supported"]
    assert body["transparency_bg"] == "#FFFFFF"
    assert body["output_format"] == "JPEG"


def test_index(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "AI Image Upscaler" in res.text
    assert "Supported: JPG, PNG, WebP, ZIP" in res.text
    assert "Upscale" in res.text
    assert "Output size" in res.text
