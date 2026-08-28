"""EasyModelGate 命令行入口（规格 §47-§49）。

子命令：serve / user {create,list,disable,enable} /
        key {create,list,disable,enable} / usage summary
完整 Key 仅在 key create 的 stdout 展示一次。
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import AppConfig, load_config
from .core.security import mask_key
from .db.database import Database
from .services import usage_service
from .services import user_service, key_service
from .services.analytics import SummaryFilter


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="easymodelgate",
        description="EasyModelGate：轻量级本地模型 API 网关")
    parser.add_argument("--config", help="TOML 配置文件路径")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("serve", help="启动网关服务")

    user_p = sub.add_parser("user", help="用户管理")
    user_sub = user_p.add_subparsers(dest="user_cmd", required=True)
    u_create = user_sub.add_parser("create", help="创建用户")
    u_create.add_argument("--username", required=True)
    u_create.add_argument("--display-name")
    u_create.add_argument("--note")
    user_sub.add_parser("list", help="列出用户")
    u_disable = user_sub.add_parser("disable", help="停用用户")
    u_disable.add_argument("--username", required=True)
    u_enable = user_sub.add_parser("enable", help="启用用户")
    u_enable.add_argument("--username", required=True)

    key_p = sub.add_parser("key", help="API Key 管理")
    key_sub = key_p.add_subparsers(dest="key_cmd", required=True)
    k_create = key_sub.add_parser("create", help="创建 API Key（完整 Key 仅展示一次）")
    k_create.add_argument("--user", required=True, help="所属用户名")
    k_create.add_argument("--name", help="备注名")
    k_create.add_argument("--rpm", type=int, help="每分钟请求数限制")
    k_create.add_argument("--token-limit", type=int, dest="token_limit",
                          help="Token 软额度上限")
    k_create.add_argument("--expires-in-days", type=int, dest="expires_in_days",
                          help="N 天后过期；不填永不过期")
    k_list = key_sub.add_parser("list", help="列出 Key（脱敏）")
    k_list.add_argument("--user", help="按用户名过滤")
    k_disable = key_sub.add_parser("disable", help="停用 Key（按前缀，需唯一匹配）")
    k_disable.add_argument("prefix")
    k_enable = key_sub.add_parser("enable", help="启用 Key（按前缀，需唯一匹配）")
    k_enable.add_argument("prefix")
    k_limits = key_sub.add_parser("set-limits", help="修改 Key 的 RPM / Token 限额")
    k_limits.add_argument("prefix", help="Key 前缀（需唯一匹配）")
    k_limits.add_argument("--rpm", type=int, help="RPM 限额；--clear-rpm 清除")
    k_limits.add_argument("--token-limit", type=int, dest="token_limit",
                          help="Token 软额度；--clear-token-limit 清除")
    k_limits.add_argument("--clear-rpm", action="store_true")
    k_limits.add_argument("--clear-token-limit", action="store_true")

    usage_p = sub.add_parser("usage", help="用量统计")
    usage_sub = usage_p.add_subparsers(dest="usage_cmd", required=True)
    us = usage_sub.add_parser("summary", help="用量汇总")
    us.add_argument("--period",
                    choices=["today", "yesterday", "24h", "7d", "week", "month", "all"])
    us.add_argument("--from", dest="from_str", help='起始时间（配置时区），如 "2026-08-01 00:00"')
    us.add_argument("--to", dest="to_str", help='结束时间（配置时区）')
    us.add_argument("--group-by", choices=["hour", "day", "week", "month", "none"],
                    default=None)
    us.add_argument("--user", help="按用户名过滤")
    us.add_argument("--key", help="按 Key 前缀过滤")
    us.add_argument("--model", help="按模型名过滤")

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        return _serve(args)

    cfg = load_config(args.config)
    try:
        return asyncio.run(_run_cli(cfg, args))
    except KeyboardInterrupt:
        return 130


def _serve(args) -> int:
    import uvicorn
    from .app import create_app

    cfg = load_config(args.config)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run(
        create_app(cfg),
        host=cfg.server.host,
        port=cfg.server.port,
        limit_concurrency=cfg.limits.max_client_concurrency,
    )
    return 0


async def _run_cli(cfg: AppConfig, args) -> int:
    db = await Database(cfg.database.path).connect()
    try:
        if args.cmd == "user":
            return await _user(db, args)
        if args.cmd == "key":
            return await _key(cfg, db, args)
        if args.cmd == "usage":
            return await _usage(cfg, db, args)
        raise ValueError(f"未知命令 {args.cmd}")
    finally:
        await db.close()


# ---------- user ----------

async def _user(db: Database, args) -> int:
    if args.user_cmd == "create":
        try:
            uid = await user_service.create_user(
                db, args.username, args.display_name, args.note)
        except user_service.UserAlreadyExists as e:
            print(f"错误：用户 {e.username} 已存在")
            return 1
        print(f"用户已创建：id={uid}  username={args.username}")
        return 0
    if args.user_cmd == "list":
        rows = await user_service.list_users(db)
        print(f"{'id':>4}  {'enabled':<7}  {'username':<20}  {'display_name':<16}  created_at(ms)")
        for r in rows:
            print(f"{r['id']:>4}  {str(bool(r['enabled'])):<7}  "
                  f"{r['username']:<20}  {(r['display_name'] or '-'):<16}  {r['created_at']}")
        return 0
    enabled = args.user_cmd == "enable"
    try:
        await user_service.set_user_enabled(db, args.username, enabled)
    except user_service.UserNotFound as e:
        print(f"错误：用户 {e.username} 不存在")
        return 1
    print(f"已完成：{args.username} -> {'启用' if enabled else '停用'}")
    return 0


# ---------- key ----------

async def _key(cfg: AppConfig, db: Database, args) -> int:
    if args.key_cmd == "create":
        try:
            user = await user_service.require_user(db, args.user)
        except user_service.UserNotFound:
            print(f"错误：用户 {args.user} 不存在，请先 user create")
            return 1
        kid, full, masked = await key_service.create_key(
            db, user_id=int(user["id"]), name=args.name, rpm=args.rpm,
            token_limit=args.token_limit, expires_in_days=args.expires_in_days,
            timezone=cfg.usage.timezone, key_prefix=cfg.security.key_prefix)
        print("请立即保存，该 Key 后续无法再次查看。")
        print()
        print(full)
        print()
        print(f"标识：{masked}   key_id={kid}   user={args.user}")
        return 0
    if args.key_cmd == "list":
        uid = None
        if getattr(args, "user", None):
            try:
                uid = int((await user_service.require_user(db, args.user))["id"])
            except user_service.UserNotFound:
                print(f"错误：用户 {args.user} 不存在")
                return 1
        rows = await key_service.list_keys(db, uid)
        users = {u["id"]: u["username"] for u in await user_service.list_users(db)}
        print(f"{'id':>4}  {'user':<14}  {'name':<12}  {'key_prefix':<14}  "
              f"{'enabled':<7}  {'rpm':>5}  {'tok_used':>9}  {'tok_limit':>10}  "
              f"expires_at  last_used_at")
        for r in rows:
            print(f"{r['id']:>4}  {users.get(r['user_id'], '-'):<14}  "
                  f"{(r['name'] or '-'):<12}  {mask_key(r['key_prefix']):<14}  "
                  f"{str(bool(r['enabled'])):<7}  "
                  f"{str(r['rpm_limit'] if r['rpm_limit'] is not None else '-'):>5}  "
                  f"{r['token_used']:>9}  "
                  f"{str(r['token_limit'] if r['token_limit'] is not None else '-'):>10}  "
                  f"{r['expires_at'] or '-'}  {r['last_used_at'] or '-'}")
        return 0
    # enable / disable / set-limits：前缀唯一匹配 → key_id → 共享 by-id 操作
    try:
        target = await key_service.resolve_key_prefix(db, args.prefix)
    except key_service.AmbiguousKeyPrefix as e:
        print(f"错误：前缀 {e.prefix} 匹配到 {e.count} 个 Key（需恰好 1 个）")
        return 1
    if args.key_cmd in ("enable", "disable"):
        await key_service.set_key_enabled(db, int(target["id"]),
                                          args.key_cmd == "enable")
        print(f"已完成：key_id={target['id']} ({mask_key(target['key_prefix'])}) -> "
              f"{'启用' if args.key_cmd == 'enable' else '停用'}")
        return 0
    # set-limits
    rpm = (key_service.CLEAR if args.clear_rpm
           else key_service.KEEP if args.rpm is None else args.rpm)
    tok = (key_service.CLEAR if args.clear_token_limit
           else key_service.KEEP if args.token_limit is None else args.token_limit)
    _, new_rpm, new_tok = await key_service.set_key_limits(
        db, int(target["id"]), rpm=rpm, token_limit=tok)
    print(f"已完成：key_id={target['id']} ({mask_key(target['key_prefix'])}) "
          f"rpm_limit={new_rpm} token_limit={new_tok}")
    return 0


# ---------- usage ----------

_TABLE_HEADERS = ["时间段", "请求数", "成功", "失败",
                  "prompt", "completion", "total", "cached",
                  "平均耗时ms", "平均排队ms", "最大排队ms", "平均upstream ms", "平均TTFT ms"]


async def _usage(cfg: AppConfig, db: Database, args) -> int:
    tz_name = cfg.usage.timezone
    start_ms, end_ms, default_group = usage_service.resolve_time_range(
        args.period, args.from_str, args.to_str, tz_name)
    group_by = args.group_by or default_group
    try:
        user_id, api_key_id = await usage_service.resolve_filters(
            db, username=args.user, key_prefix=args.key)
    except user_service.UserNotFound as e:
        print(f"错误：用户 {e.username} 不存在")
        return 1
    except key_service.AmbiguousKeyPrefix as e:
        print(f"错误：--key {e.prefix} 匹配到 {e.count} 个 Key（需恰好 1 个）")
        return 1

    f = SummaryFilter(
        start_ms=start_ms, end_ms=end_ms, user_id=user_id, api_key_id=api_key_id,
        model=args.model, granularity=None if group_by == "none" else group_by,
        timezone=tz_name)
    rows = await usage_service.summarize(db, f)

    print("EasyModelGate 用量汇总（时间均为本地时区 %s）" % tz_name)
    print("  ".join(f"{h}" for h in _TABLE_HEADERS))
    for r in rows:
        cells = [
            str(r["bucket"]),
            str(r["requests"]),
            str(r["success_count"]), str(r["error_count"]),
            _fmt(r["prompt_tokens"]), _fmt(r["completion_tokens"]),
            _fmt(r["total_tokens"]), _fmt(r["cached_tokens"]),
            _fmt_avg(r["avg_duration_ms"]), _fmt_avg(r["avg_queue_wait_ms"]),
            _fmt_avg(r.get("max_queue_wait_ms")),
            _fmt_avg(r["avg_upstream_duration_ms"]), _fmt_avg(r["avg_ttft_ms"]),
        ]
        print("  ".join(cells))
    return 0


def _fmt(v) -> str:
    return "-" if v is None else str(int(v))


def _fmt_avg(v) -> str:
    return "-" if v is None else f"{v:.1f}"



if __name__ == "__main__":
    sys.exit(main())
