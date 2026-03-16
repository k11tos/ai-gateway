import app


def test_presets_endpoint_json_structure(client):
    response = client.get("/presets")

    assert response.status_code == 200
    payload = response.json()

    assert set(payload.keys()) == {"presets"}
    assert isinstance(payload["presets"], list)

    for preset in payload["presets"]:
        assert set(preset.keys()) == {"name", "description", "prompt_prefix"}
        assert isinstance(preset["name"], str)
        assert isinstance(preset["description"], str)
        assert isinstance(preset["prompt_prefix"], str)


def test_presets_endpoint_includes_prompt_prefix(client):
    response = client.get("/presets")

    assert response.status_code == 200
    assert response.json() == {
        "presets": [
            {
                "name": preset["name"],
                "description": preset["description"],
                "prompt_prefix": preset["prompt_prefix"],
            }
            for preset in app.PRESET_DEFINITIONS
        ]
    }


def test_presets_endpoint_response_is_stable(client):
    first_response = client.get("/presets")
    second_response = client.get("/presets")

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == second_response.json()
