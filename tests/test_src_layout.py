def test_src_package_imports():
    import warp2api
    from warp2api.app.main import main  # noqa: F401
    from warp2api.app.bridge import app as bridge_app  # noqa: F401
    from warp2api.app.openai import openai_app  # noqa: F401
    from warp2api.infrastructure.settings.config import Settings

    assert hasattr(warp2api, "__all__")
    assert Settings().warp_url.startswith("https://")
