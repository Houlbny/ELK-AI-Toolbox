from mcp_server.server import build_overrides, parse_args


def test_parse_args_defaults():
    args = parse_args([])

    assert args.mode is None
    assert args.timeout is None
    assert args.max_results is None
    assert args.max_time_range is None
    assert args.max_buckets is None
    assert args.verify_certs is None


def test_parse_args_with_values():
    args = parse_args(
        [
            "--mode",
            "kibana",
            "--timeout",
            "45s",
            "--max-results",
            "25",
            "--max-time-range",
            "10d",
            "--max-buckets",
            "30",
            "--verify-certs",
            "false",
        ]
    )

    assert args.mode == "kibana"
    assert args.timeout == "45s"
    assert args.max_results == 25
    assert args.max_time_range == "10d"
    assert args.max_buckets == 30
    assert args.verify_certs == "false"


def test_build_overrides_only_contains_provided_args():
    args = parse_args(["--timeout", "50s", "--max-results", "5"])

    overrides = build_overrides(args)

    assert overrides == {
        "timeout": "50s",
        "max_results": 5,
    }


def test_build_overrides_includes_max_buckets():
    args = parse_args(["--max-buckets", "40"])

    overrides = build_overrides(args)

    assert overrides == {"max_buckets": 40}
