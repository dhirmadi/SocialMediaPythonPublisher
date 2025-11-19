from __future__ import annotations

from fastapi.testclient import TestClient

from publisher_v2.web.app import app


def _get_index_html() -> str:
    client = TestClient(app)
    res = client.get("/")
    assert res.status_code == 200
    return res.text


def test_web_index_responsive_renders_image_container() -> None:
    html = _get_index_html()
    assert 'class="image-container"' in html
    assert 'id="image"' in html


def test_web_index_responsive_img_styles_mobile() -> None:
    html = _get_index_html()
    # Ensure the CSS includes responsive rules for the image container and image
    assert ".image-container {" in html
    assert "max-width: min(100%, 1280px);" in html
    assert ".image-container img" in html
    assert "max-width: 100%;" in html
    assert "height: auto;" in html


