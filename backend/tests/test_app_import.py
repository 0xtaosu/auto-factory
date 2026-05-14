def test_app_imports():
    from app.main import app

    assert app.title == "库存健康度 Demo API"
