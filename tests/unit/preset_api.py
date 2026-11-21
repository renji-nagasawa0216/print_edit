"""仕様テスト用。公開APIで組み込みの「既定」を読み書きする。"""


def builtin_preset(client):
    response = client.get("/api/presets")
    assert response.status_code == 200, response.text
    preset, = (row for row in response.json() if row["builtin"])
    return preset


def get_preset_data(client):
    return builtin_preset(client)["data"]


def put_preset_data(client, data):
    preset_id = builtin_preset(client)["id"]
    return client.put(f"/api/presets/{preset_id}", json={"data": data})
