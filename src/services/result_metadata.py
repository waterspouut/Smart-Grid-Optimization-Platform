# 서비스 결과 메타데이터 형식을 공통 규칙으로 맞춘다.
from __future__ import annotations

from src.data.schemas import FallbackInfo, FallbackMode


def build_fallback_warning(
    service_name: str,
    mode: FallbackMode,
) -> str:
    """서비스별 fallback 경고 첫 문구 형식을 통일한다."""

    return f"{service_name}는 현재 `{mode}` fallback 결과를 반환합니다."


def build_source_warning(
    service_name: str,
    source_name: str,
) -> str:
    """fallback 이 없는 정상 경로 결과 안내 문구."""

    return f"{service_name}는 현재 `{source_name}` 결과를 반환합니다."


def build_fallback_info(
    *,
    mode: FallbackMode,
    reason: str,
    primary_path: str,
    active_path: str,
) -> FallbackInfo:
    """fallback 사용 중인 결과 메타데이터를 공통 생성한다."""

    return FallbackInfo(
        enabled=True,
        mode=mode,
        reason=reason,
        primary_path=primary_path,
        active_path=active_path,
    )


def build_no_fallback_info() -> FallbackInfo:
    """정상 경로 결과 메타데이터를 공통 생성한다."""

    return FallbackInfo(enabled=False, mode="none")
