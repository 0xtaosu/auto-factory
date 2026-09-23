def test_app_imports():
    from app.main import app

    assert app.title == "物料活跃度 MVP API"
