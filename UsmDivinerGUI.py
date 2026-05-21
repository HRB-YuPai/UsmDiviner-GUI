if __name__ == "__main__":
    try:
        from usmdiviner.gui import main
    except ModuleNotFoundError as exc:
        if exc.name and exc.name.startswith("PySide6"):
            print(
                "WebQt GUI requires PySide6 (including QtWebEngine). "
                "Install with: pip install PySide6"
            )
            raise SystemExit(2)
        raise
    raise SystemExit(main())
