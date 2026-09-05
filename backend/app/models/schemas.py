"""Pydantic schemas for the render request and job status."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Position = Literal["top", "center", "bottom"]
Align = Literal["center", "start"]


class BackgroundClip(BaseModel):
    id: str
    sourceId: str
    trimStart: float = Field(0, ge=0)
    trimEnd: float = Field(0, ge=0)  # 0 = use the rest of the source


class BackgroundSettings(BaseModel):
    id: str = "night-sky"                      # filename stem (builtin or uploaded)
    brightness: int = Field(80, ge=20, le=150)  # percent, 100 = unchanged
    contrast: int = Field(100, ge=20, le=200)
    saturation: int = Field(90, ge=0, le=200)
    blur: int = Field(0, ge=0, le=40)          # px radius
    darkOverlay: int = Field(42, ge=0, le=90)  # percent black overlay
    position: Position = "center"
    clips: list[BackgroundClip] = Field(default_factory=list)
    crossfade: bool = True
    transitionDuration: float = Field(0.5, ge=0.2, le=1.0)


class CardSettings(BaseModel):
    visible: bool = True
    color: str = "#0a0c12"                     # hex
    opacity: int = Field(70, ge=0, le=100)
    radius: int = Field(24, ge=0, le=64)
    borderWidth: int = Field(0, ge=0, le=6)
    borderColor: str = "#c9a45c"
    widthPct: int = Field(92, ge=50, le=96)    # of 1080
    padding: int = Field(32, ge=16, le=120)
    positionPct: int = Field(52, ge=20, le=80) # vertical center of card


class ArabicTextSettings(BaseModel):
    font: str = "amiri"
    size: int = Field(68, ge=36, le=140)
    color: str = "#f5f1e8"
    lineHeight: float = Field(1.85, ge=0, le=5)
    offsetX: float = Field(0, ge=-40, le=40)  # % of canvas width from default
    offsetY: float = Field(0, ge=-40, le=40)  # % of canvas height from default


class TranslationSettings(BaseModel):
    font: str = "amiri"
    size: int = Field(40, ge=20, le=64)
    color: str = "#d8d2c4"
    lineHeight: float = Field(1.5, ge=0, le=5)
    offsetX: float = Field(0, ge=-40, le=40)
    offsetY: float = Field(0, ge=-40, le=40)


class HeaderSettings(BaseModel):
    show: bool = True
    showArabic: bool = True
    showEnglish: bool = True
    showNumber: bool = True
    topPct: int = Field(7, ge=3, le=30)  # header top, % of canvas height
    size: int = Field(64, ge=28, le=96)   # Arabic name size at 1080×1920
    gap: int = Field(18, ge=4, le=48)     # space between Arabic and English names
    color: str = "#f5f1e8"               # same ink as the Arabic verse by default
    lineHeight: float = Field(1.2, ge=0, le=5)


class TextSettings(BaseModel):
    card: CardSettings = CardSettings()
    arabic: ArabicTextSettings = ArabicTextSettings()
    translation: TranslationSettings = TranslationSettings()
    header: HeaderSettings = HeaderSettings()
    showAyahNumber: bool = True
    refColor: str = "#c9a45c"
    outline: bool = False


class RenderRequest(BaseModel):
    surah: int = Field(..., ge=1, le=114)
    fromAyah: int = Field(..., ge=1)
    toAyah: int = Field(..., ge=1)
    reciter: str = "alafasy"
    translation: str = "en-sahih"
    platform: Literal["tiktok", "shorts", "reels", "youtube", "portrait", "square"] = "tiktok"
    resolution: Literal["light", "fhd", "uhd"] = "fhd"  # 0.5x / 1x / 2x of platform dims
    quality: Literal["max", "high", "small"] = "high"  # x264 trade-off tiers
    withLight: bool = False  # also emit a 540-class copy for WhatsApp/small players
    background: BackgroundSettings = BackgroundSettings()
    text: TextSettings = TextSettings()
    fadeMs: int = Field(280, ge=120, le=600)


class PreviewTimelineRequest(BaseModel):
    surah: int = Field(..., ge=1, le=114)
    fromAyah: int = Field(..., ge=1)
    toAyah: int = Field(..., ge=1)
    reciter: str = "alafasy"
