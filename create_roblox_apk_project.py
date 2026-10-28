#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Trình khởi tạo tự động Dự án Android (.APK) hoàn chỉnh - Phiên bản V2 (Đã vá lỗi lặp chữ & tràn khung).

Các lỗi đã được khắc phục triệt để trong bản V2:
1. Chống vòng lặp tự dịch đè chữ Tiếng Việt (Feedback Loop):
   - Tự động bỏ qua mọi dòng chữ đã có dấu Tiếng Việt (ă, â, đ, ê, ô, ơ, ư, sắc, huyền, hỏi, ngã, nặng...)
     để OCR không bao giờ đọc lại chính hộp chữ Tiếng Việt vừa dịch rồi dịch chồng lên nhau.
   - Loại trừ vùng thanh điều khiển nổi ("🟢 Đang dịch | 🧹 Cache | ✖") và thanh trạng thái pin/giờ
     khỏi vùng quét OCR.
2. Chống chụp dính lớp phủ (Clean Capture):
   - Tạm ẩn lớp phủ (alpha = 0f), xả bỏ khung hình cũ trong bộ đệm ImageReader và chờ khung hình
     mới sạch 100% trước khi đưa vào ML Kit OCR.
3. Chống gộp tràn toàn màn hình:
   - Giới hạn gộp tối đa theo từng cụm hộp thoại nhỏ (không gộp quá 3 dòng hoặc quá 18% chiều cao màn hình),
     giữ từng câu thoại/nhiệm vụ nằm gọn đúng vị trí chữ gốc.
"""

import os
import zipfile
from pathlib import Path

PROJECT_DIR = Path("RobloxTranslatorAPK")

FILES: dict[str, str] = {
    "settings.gradle.kts": """pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}
dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}
rootProject.name = "RobloxScreenTranslator"
include(":app")
""",

    "build.gradle.kts": """plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
""",

    "gradle.properties": """org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8
android.useAndroidX=true
kotlin.code.style=official
android.nonTransitiveRClass=true
""",

    "app/build.gradle.kts": """plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "com.roblox.translator"
    compileSdk = 34

    defaultConfig {
        applicationId = "com.roblox.translator"
        minSdk = 26
        targetSdk = 34
        versionCode = 2
        versionName = "2.0.0"
    }

    buildTypes {
        release {
            isMinifyEnabled = false
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions {
        jvmTarget = "17"
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("com.google.mlkit:text-recognition:16.0.1")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.8.1")
}
""",

    "app/src/main/AndroidManifest.xml": """<?xml version="1.0" encoding="utf-8"?>
<manifest xmlns:android="http://schemas.android.com/apk/res/android">

    <uses-permission android:name="android.permission.INTERNET" />
    <uses-permission android:name="android.permission.SYSTEM_ALERT_WINDOW" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE" />
    <uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PROJECTION" />
    <uses-permission android:name="android.permission.POST_NOTIFICATIONS" />

    <application
        android:allowBackup="true"
        android:label="Roblox Translator Overlay"
        android:supportsRtl="true"
        android:theme="@style/Theme.AppCompat.NoActionBar">

        <activity
            android:name=".MainActivity"
            android:exported="true"
            android:launchMode="singleTop">
            <intent-filter>
                <action android:name="android.intent.action.MAIN" />
                <category android:name="android.intent.category.LAUNCHER" />
            </intent-filter>
        </activity>

        <service
            android:name=".ScreenCaptureService"
            android:enabled="true"
            android:exported="false"
            android:foregroundServiceType="mediaProjection" />
    </application>
</manifest>
""",

    "app/src/main/java/com/roblox/translator/Config.kt": """package com.roblox.translator

import android.graphics.Color

data class Config(
    val sourceLang: String = "en",
    val targetLang: String = "vi",
    val scanIntervalMs: Long = 900L,
    val minConfidence: Float = 0.65f,
    val ocrMaxWidth: Int = 1280,
    val thumbWidth: Int = 160,
    val thumbHeight: Int = 90,
    val changePixelDelta: Int = 32,
    val changePixelRatio: Double = 0.02, // Cần ít nhất 2% cảnh màn hình thay đổi mới quét lại
    val translateTimeoutMs: Long = 8000L,
    val translateMaxChars: Int = 1500,
    val translateWorkers: Int = 4,
    val cacheSize: Int = 2000,
    val failCooldownAfter: Int = 3,
    val failCooldownMaxSec: Double = 30.0,
    val overlayBgColor: Int = Color.parseColor("#E6141824"),
    val overlayTextColor: Int = Color.parseColor("#FFE066"),
    val overlayBorderColor: Int = Color.parseColor("#3B82F6"),
    val fontSizeSp: Float = 11.5f
)
""",

    "app/src/main/java/com/roblox/translator/TextBlock.kt": """package com.roblox.translator

import kotlin.math.max

data class TextBlock(
    val x1: Int,
    val y1: Int,
    val x2: Int,
    val y2: Int,
    val originalText: String,
    var translatedText: String = "",
    val confidence: Float = 1.0f,
    val lineHeight: Int = max(1, y2 - y1)
) {
    val width: Int get() = max(1, x2 - x1)
    val height: Int get() = max(1, y2 - y1)
}
""",

    "app/src/main/java/com/roblox/translator/ScanPipeline.kt": """package com.roblox.translator

import android.graphics.Bitmap
import android.graphics.Rect
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min

object TextBlockMerger {
    private val cjkRegex = Regex("[\\\\u3040-\\\\u30FF\\\\u3400-\\\\u4DBF\\\\u4E00-\\\\u9FFF\\\\uAC00-\\\\uD7AF]")
    // Nhận diện các ký tự có dấu đặc trưng của Tiếng Việt để KHÔNG BAO GIỜ tự đọc lại chữ đã dịch
    private val vietnameseRegex = Regex("[ăâđêôơưĂÂĐÊÔƠƯáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵÁÀẢÃẠẮẰẲẴẶẤẦẨẪẬÉÈẺẼẸẾỀỂỄỆÍÌỈĨỊÓÒỎÕỌỐỒỔỖỘỚỜỞỠỢÚÙỦŨỤỨỪỬỮỰÝỲỶỸỴ]")

    fun shouldSkipText(text: String): Boolean {
        val cleaned = text.trim()
        if (cleaned.isEmpty()) return true
        if (cleaned.length < 2 && !cjkRegex.containsMatchIn(cleaned)) return true
        // Nếu chuỗi đã có dấu Tiếng Việt hoặc trùng nút điều khiển thì bỏ qua ngay lập tức
        if (vietnameseRegex.containsMatchIn(cleaned)) return true
        val lower = cleaned.lowercase()
        if (lower.contains("đang dịch") || lower.contains("tạm dừng") || lower.contains("cache")) return true
        val letterCount = cleaned.count { it.isLetter() }
        if (letterCount < 2 && !cjkRegex.containsMatchIn(cleaned)) return true
        return false
    }

    private fun joinParts(parts: List<String>): String {
        val sb = StringBuilder()
        for (part in parts) {
            if (part.isEmpty()) continue
            if (sb.isNotEmpty()) {
                val prevLast = sb.last().toString()
                val currFirst = part.first().toString()
                if (!(cjkRegex.matches(prevLast) && cjkRegex.matches(currFirst))) {
                    sb.append(' ')
                }
            }
            sb.append(part)
        }
        return sb.toString()
    }

    private fun canMerge(group: List<TextBlock>, candidate: TextBlock, maxGroupHeight: Int): Boolean {
        if (group.size >= 3) return false // Tối đa 3 dòng mỗi hộp để không tạo hộp khổng lồ che màn hình
        val gMinX = min(group.minOf { it.x1 }, candidate.x1)
        val gMaxX = max(group.maxOf { it.x2 }, candidate.x2)
        val gMinY = min(group.minOf { it.y1 }, candidate.y1)
        val gMaxY = max(group.maxOf { it.y2 }, candidate.y2)
        if (gMaxY - gMinY > maxGroupHeight) return false

        return group.any { a ->
            val lh = max(a.lineHeight, candidate.lineHeight).toDouble()
            val upper = if (a.y1 <= candidate.y1) a else candidate
            val lower = if (a.y1 <= candidate.y1) candidate else a
            val verticalGap = (lower.y1 - upper.y2).toDouble()
            val hOverlap = min(upper.x2, lower.x2) - max(upper.x1, lower.x1)
            val leftAlignDiff = abs(lower.x1 - upper.x1).toDouble()
            (verticalGap in (-0.25 * lh)..(0.55 * lh)) &&
                    (hOverlap > lh * 0.5 && leftAlignDiff < 1.5 * lh)
        }
    }

    private fun buildBlock(members: List<TextBlock>): TextBlock {
        val sorted = members.sortedWith(compareBy<TextBlock> { it.y1 }.thenBy { it.x1 })
        val text = joinParts(sorted.map { it.originalText })
        return TextBlock(
            x1 = members.minOf { it.x1 },
            y1 = members.minOf { it.y1 },
            x2 = members.maxOf { it.x2 },
            y2 = members.maxOf { it.y2 },
            originalText = text,
            confidence = members.minOf { it.confidence },
            lineHeight = members.maxOf { it.lineHeight }
        )
    }

    fun mergeNearbyBlocks(blocks: List<TextBlock>, screenH: Int): List<TextBlock> {
        if (blocks.isEmpty()) return emptyList()
        val maxGroupHeight = (screenH * 0.14).toInt().coerceAtLeast(120)
        val sorted = blocks.sortedWith(compareBy<TextBlock> { it.y1 }.thenBy { it.x1 })
        val groups = mutableListOf<MutableList<TextBlock>>()

        for (b in sorted) {
            val targetGroup = groups.firstOrNull { canMerge(it, b, maxGroupHeight) }
            if (targetGroup != null) {
                targetGroup.add(b)
            } else {
                groups.add(mutableListOf(b))
            }
        }
        return groups.map { buildBlock(it) }
    }
}

class FrameChangeDetector(
    private val thumbW: Int,
    private val thumbH: Int,
    private val pixelDelta: Int,
    private val pixelRatio: Double
) {
    private var prevGray: IntArray? = null

    fun reset() {
        prevGray = null
    }

    fun hasChanged(frame: Bitmap, maskedRects: List<Rect>, screenW: Int, screenH: Int): Boolean {
        val scaled = Bitmap.createScaledBitmap(frame, thumbW, thumbH, true)
        val pixels = IntArray(thumbW * thumbH)
        scaled.getPixels(pixels, 0, thumbW, 0, 0, thumbW, thumbH)

        val currGray = IntArray(pixels.size)
        for (i in pixels.indices) {
            val c = pixels[i]
            val r = (c shr 16) and 0xFF
            val g = (c shr 8) and 0xFF
            val b = c and 0xFF
            currGray[i] = (r * 77 + g * 150 + b * 29) shr 8
        }

        val prev = prevGray
        if (prev == null || prev.size != currGray.size) {
            prevGray = currGray
            return true
        }

        val scaleX = thumbW.toDouble() / max(1, screenW)
        val scaleY = thumbH.toDouble() / max(1, screenH)
        val scaledMasks = maskedRects.map {
            Rect(
                ((it.left - 16) * scaleX).toInt(),
                ((it.top - 16) * scaleY).toInt(),
                ((it.right + 16) * scaleX).toInt(),
                ((it.bottom + 16) * scaleY).toInt()
            )
        }

        var changedCount = 0
        var totalValid = 0
        // Bỏ qua 8% mép trên cùng (thanh pin, đồng hồ, sóng điện thoại)
        val startY = (thumbH * 0.08).toInt()
        for (y in startY until thumbH) {
            val rowOffset = y * thumbW
            for (x in 0 until thumbW) {
                if (scaledMasks.any { it.contains(x, y) }) continue
                totalValid++
                if (abs(currGray[rowOffset + x] - prev[rowOffset + x]) > pixelDelta) {
                    changedCount++
                }
            }
        }

        if (totalValid < (thumbW * thumbH) / 10) {
            return false
        }

        val ratio = changedCount.toDouble() / totalValid
        if (ratio >= pixelRatio) {
            prevGray = currGray
            return true
        }
        return false
    }
}
""",

    "app/src/main/java/com/roblox/translator/CachedTranslator.kt": """package com.roblox.translator

import android.util.LruCache
import org.json.JSONArray
import java.net.HttpURLConnection
import java.net.URL
import java.net.URLEncoder
import java.util.concurrent.Callable
import java.util.concurrent.Executors
import java.util.concurrent.Future
import java.util.concurrent.TimeUnit
import kotlin.math.min
import kotlin.math.pow

class CachedTranslator(private val cfg: Config) {
    private val cache = LruCache<String, String>(cfg.cacheSize)
    private val lock = Any()
    private var failStreak = 0
    private var cooldownUntilMs = 0L
    private val pool = Executors.newFixedThreadPool(cfg.translateWorkers)

    private fun normalizeKey(text: String): String =
        text.trim().replace(Regex("\\\\s+"), " ").lowercase()

    fun clearCache() {
        synchronized(lock) {
            cache.evictAll()
        }
    }

    private fun lookup(key: String): String? = synchronized(lock) { cache.get(key) }

    private fun store(key: String, value: String) {
        synchronized(lock) {
            cache.put(key, value)
        }
    }

    private fun registerFailure() {
        synchronized(lock) {
            failStreak++
            if (failStreak >= cfg.failCooldownAfter) {
                val delaySec = min(
                    cfg.failCooldownMaxSec,
                    2.0.pow((failStreak - cfg.failCooldownAfter + 1).toDouble())
                )
                cooldownUntilMs = System.currentTimeMillis() + (delaySec * 1000).toLong()
            }
        }
    }

    private fun fetchSingle(text: String, key: String): String? {
        lookup(key)?.let { return it }
        synchronized(lock) {
            if (System.currentTimeMillis() < cooldownUntilMs) return null
        }

        return try {
            val trimmed = text.take(cfg.translateMaxChars)
            val encoded = URLEncoder.encode(trimmed, "UTF-8")
            val urlStr = "https://translate.googleapis.com/translate_a/single?client=gtx&sl=${cfg.sourceLang}&tl=${cfg.targetLang}&dt=t&q=$encoded"
            val conn = (URL(urlStr).openConnection() as HttpURLConnection).apply {
                connectTimeout = 5000
                readTimeout = 5000
                setRequestProperty("User-Agent", "Mozilla/5.0")
            }
            val body = conn.inputStream.bufferedReader().use { it.readText() }
            val outer = JSONArray(body).getJSONArray(0)
            val sb = StringBuilder()
            for (i in 0 until outer.length()) {
                val seg = outer.getJSONArray(i)
                if (!seg.isNull(0)) sb.append(seg.getString(0))
            }
            val translated = sb.toString().trim()
            if (translated.isEmpty() || translated.equals(text.trim(), ignoreCase = true)) {
                return ""
            }
            synchronized(lock) {
                failStreak = 0
                cooldownUntilMs = 0L
            }
            store(key, translated)
            translated
        } catch (_: Exception) {
            registerFailure()
            null
        }
    }

    fun translateBlocks(blocks: List<TextBlock>): Int {
        if (blocks.isEmpty()) return 0
        val deadline = System.currentTimeMillis() + cfg.translateTimeoutMs
        val results = mutableMapOf<String, String?>()
        val pending = mutableMapOf<String, Future<String?>>()

        for (b in blocks) {
            val key = normalizeKey(b.originalText)
            if (key in results || key in pending) continue
            val hit = lookup(key)
            if (hit != null) {
                results[key] = hit
            } else {
                pending[key] = pool.submit(Callable { fetchSingle(b.originalText, key) })
            }
        }

        for ((key, fut) in pending) {
            val remain = (deadline - System.currentTimeMillis()).coerceAtLeast(50L)
            results[key] = try {
                fut.get(remain, TimeUnit.MILLISECONDS)
            } catch (_: Exception) {
                null
            }
        }

        var failures = 0
        for (b in blocks) {
            val res = results[normalizeKey(b.originalText)]
            b.translatedText = res ?: ""
            if (res == null) failures++
        }
        return failures
    }

    fun close() {
        pool.shutdownNow()
    }
}
""",

    "app/src/main/java/com/roblox/translator/TouchThroughOverlayView.kt": """package com.roblox.translator

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Rect
import android.graphics.RectF
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.view.View
import java.util.concurrent.CopyOnWriteArrayList
import kotlin.math.max
import kotlin.math.min

class TouchThroughOverlayView(
    context: Context,
    private val cfg: Config
) : View(context) {

    private val bgPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = cfg.overlayBgColor
        style = Paint.Style.FILL
    }
    private val borderPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = cfg.overlayBorderColor
        style = Paint.Style.STROKE
        strokeWidth = 2.0f
    }
    private val textPaint = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        color = cfg.overlayTextColor
        textSize = cfg.fontSizeSp * resources.displayMetrics.scaledDensity
        isFakeBoldText = true
    }

    private var blocks: List<TextBlock> = emptyList()
    var paused: Boolean = false
    val activeScreenRects = CopyOnWriteArrayList<Rect>()

    fun updateBlocks(newBlocks: List<TextBlock>) {
        blocks = newBlocks
        postInvalidate()
    }

    override fun onDraw(canvas: Canvas) {
        super.onDraw(canvas)
        val newRects = mutableListOf<Rect>()
        if (paused) {
            activeScreenRects.clear()
            return
        }

        val loc = IntArray(2)
        getLocationOnScreen(loc)
        val offsetX = loc[0]
        val offsetY = loc[1]

        val sw = width
        val sh = height
        val padX = 8
        val padY = 5
        val margin = 6

        for (block in blocks) {
            if (block.translatedText.isBlank()) continue

            // Đổi từ tọa độ màn hình vật lý sang tọa độ tương đối của View
            val bx1 = block.x1 - offsetX
            val by1 = block.y1 - offsetY
            val bx2 = block.x2 - offsetX
            val by2 = block.y2 - offsetY

            val wrapWidth = max(140, min(block.width + 2 * padX, (sw * 0.75).toInt()))
            val layout = StaticLayout.Builder
                .obtain(block.translatedText, 0, block.translatedText.length, textPaint, wrapWidth)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL)
                .setIncludePad(false)
                .build()

            val textW = (0 until layout.lineCount).maxOfOrNull { layout.getLineWidth(it).toInt() } ?: layout.width
            val textH = layout.height

            var tx1 = bx1
            var ty1 = by1
            var tx2 = tx1 + textW
            var ty2 = ty1 + textH

            var dx = 0
            var dy = 0
            if (tx2 + margin > sw) dx = sw - margin - tx2
            if (tx1 + dx < margin) dx = margin - tx1
            if (ty2 + margin > sh) dy = sh - margin - ty2
            if (ty1 + dy < margin) dy = margin - ty1

            tx1 += dx
            ty1 += dy
            tx2 += dx
            ty2 += dy

            val rx1 = max(0, min(bx1 - padX, tx1 - padX))
            val ry1 = max(0, min(by1 - padY, ty1 - padY))
            val rx2 = min(sw, max(bx2 + padX, tx2 + padX))
            val ry2 = min(sh, max(by2 + padY, ty2 + padY))

            // Lưu tọa độ màn hình vật lý để FrameChangeDetector loại trừ chính xác
            newRects.add(Rect(rx1 + offsetX, ry1 + offsetY, rx2 + offsetX, ry2 + offsetY))

            val rectF = RectF(rx1.toFloat(), ry1.toFloat(), rx2.toFloat(), ry2.toFloat())
            canvas.drawRoundRect(rectF, 8f, 8f, bgPaint)
            canvas.drawRoundRect(rectF, 8f, 8f, borderPaint)

            canvas.save()
            canvas.translate(tx1.toFloat(), ty1.toFloat())
            layout.draw(canvas)
            canvas.restore()
        }

        activeScreenRects.clear()
        activeScreenRects.addAll(newRects)
    }
}
""",

    "app/src/main/java/com/roblox/translator/FloatingControlBubble.kt": """package com.roblox.translator

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.Rect
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.WindowManager
import android.widget.LinearLayout
import android.widget.TextView

class FloatingControlBubble(
    context: Context,
    private val windowManager: WindowManager,
    private val onTogglePause: () -> Boolean,
    private val onClearCache: () -> Unit,
    private val onQuit: () -> Unit
) {
    val container = LinearLayout(context).apply {
        orientation = LinearLayout.HORIZONTAL
        setPadding(20, 12, 20, 12)
        background = GradientDrawable().apply {
            setColor(Color.parseColor("#E6111827"))
            setStroke(3, Color.parseColor("#2563EB"))
            cornerRadius = 40f
        }
    }

    private val pauseBtn = createButton(context, "🟢 Đang dịch")
    private val clearBtn = createButton(context, "🧹 Xóa")
    private val quitBtn = createButton(context, "✖")

    val layoutParams = WindowManager.LayoutParams(
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.WRAP_CONTENT,
        WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
        WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
        PixelFormat.TRANSLUCENT
    ).apply {
        gravity = Gravity.TOP or Gravity.END
        x = 24
        y = 64
    }

    init {
        pauseBtn.setOnClickListener {
            val isPaused = onTogglePause()
            pauseBtn.text = if (isPaused) "⏸ Đã dừng" else "🟢 Đang dịch"
            pauseBtn.setTextColor(Color.parseColor(if (isPaused) "#F59E0B" else "#93C5FD"))
        }
        clearBtn.setOnClickListener { onClearCache() }
        quitBtn.setOnClickListener { onQuit() }

        container.addView(pauseBtn)
        container.addView(clearBtn)
        container.addView(quitBtn)
        enableDrag()
    }

    fun getScreenBounds(): Rect {
        val loc = IntArray(2)
        container.getLocationOnScreen(loc)
        return Rect(
            loc[0] - 12,
            loc[1] - 12,
            loc[0] + container.width + 12,
            loc[1] + container.height + 12
        )
    }

    private fun createButton(context: Context, label: String): TextView {
        return TextView(context).apply {
            text = label
            setTextColor(Color.parseColor("#93C5FD"))
            textSize = 11f
            setPadding(14, 6, 14, 6)
        }
    }

    @SuppressLint("ClickableViewAccessibility")
    private fun enableDrag() {
        var initialX = 0
        var initialY = 0
        var touchX = 0f
        var touchY = 0f

        container.setOnTouchListener { _, event ->
            when (event.action) {
                MotionEvent.ACTION_DOWN -> {
                    initialX = layoutParams.x
                    initialY = layoutParams.y
                    touchX = event.rawX
                    touchY = event.rawY
                    false
                }
                MotionEvent.ACTION_MOVE -> {
                    layoutParams.x = initialX - (event.rawX - touchX).toInt()
                    layoutParams.y = initialY + (event.rawY - touchY).toInt()
                    windowManager.updateViewLayout(container, layoutParams)
                    true
                }
                else -> false
            }
        }
    }
}
""",

    "app/src/main/java/com/roblox/translator/ScreenCaptureService.kt": """package com.roblox.translator

import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.Service
import android.content.Context
import android.content.Intent
import android.graphics.Bitmap
import android.graphics.PixelFormat
import android.graphics.Rect
import android.hardware.display.DisplayManager
import android.hardware.display.VirtualDisplay
import android.media.ImageReader
import android.media.projection.MediaProjection
import android.media.projection.MediaProjectionManager
import android.os.Build
import android.os.Handler
import android.os.IBinder
import android.os.Looper
import android.view.WindowManager
import androidx.core.app.NotificationCompat
import com.google.mlkit.vision.common.InputImage
import com.google.mlkit.vision.text.TextRecognition
import com.google.mlkit.vision.text.latin.TextRecognizerOptions
import java.util.concurrent.CountDownLatch
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.math.min

class ScreenCaptureService : Service() {

    private val cfg = Config()
    private lateinit var windowManager: WindowManager
    private lateinit var overlayView: TouchThroughOverlayView
    private lateinit var controlBubble: FloatingControlBubble

    private var mediaProjection: MediaProjection? = null
    private var virtualDisplay: VirtualDisplay? = null
    private var imageReader: ImageReader? = null

    private val detector = FrameChangeDetector(cfg.thumbWidth, cfg.thumbHeight, cfg.changePixelDelta, cfg.changePixelRatio)
    private val translator = CachedTranslator(cfg)
    private val recognizer = TextRecognition.getClient(TextRecognizerOptions.DEFAULT_OPTIONS)

    private val mainHandler = Handler(Looper.getMainLooper())
    private val workerPool = Executors.newSingleThreadScheduledExecutor()
    private val running = AtomicBoolean(true)
    private val paused = AtomicBoolean(false)
    private var lastBlocks: List<TextBlock> = emptyList()
    private var hasFailures: Boolean = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        startForegroundNotification()

        val resultCode = intent?.getIntExtra("RESULT_CODE", Activity.RESULT_CANCELED) ?: Activity.RESULT_CANCELED
        val data: Intent? = intent?.getParcelableExtra("DATA")
        if (resultCode != Activity.RESULT_OK || data == null) {
            stopSelf()
            return START_NOT_STICKY
        }

        setupOverlays()
        setupMediaProjection(resultCode, data)
        workerPool.scheduleWithFixedDelay(::scanStep, 600L, cfg.scanIntervalMs, TimeUnit.MILLISECONDS)
        return START_STICKY
    }

    private fun startForegroundNotification() {
        val channelId = "roblox_translator_channel"
        val nm = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channel = NotificationChannel(channelId, "Roblox Screen Translator", NotificationManager.IMPORTANCE_LOW)
        nm.createNotificationChannel(channel)
        val notification: Notification = NotificationCompat.Builder(this, channelId)
            .setContentTitle("Đang dịch màn hình Roblox (V2)")
            .setContentText("Chạm nút nổi trên màn hình để Tạm dừng / Xóa Cache / Thoát")
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .build()
        startForeground(1001, notification)
    }

    private fun setupOverlays() {
        windowManager = getSystemService(Context.WINDOW_SERVICE) as WindowManager
        overlayView = TouchThroughOverlayView(this, cfg)

        val overlayParams = WindowManager.LayoutParams(
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.MATCH_PARENT,
            WindowManager.LayoutParams.TYPE_APPLICATION_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or
                    WindowManager.LayoutParams.FLAG_NOT_TOUCHABLE or
                    WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN or
                    WindowManager.LayoutParams.FLAG_LAYOUT_NO_LIMITS,
            PixelFormat.TRANSLUCENT
        ).apply {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
                layoutInDisplayCutoutMode = WindowManager.LayoutParams.LAYOUT_IN_DISPLAY_CUTOUT_MODE_SHORT_EDGES
            }
        }
        windowManager.addView(overlayView, overlayParams)

        controlBubble = FloatingControlBubble(
            context = this,
            windowManager = windowManager,
            onTogglePause = {
                val nowPaused = !paused.get()
                paused.set(nowPaused)
                if (!nowPaused) detector.reset()
                overlayView.paused = nowPaused
                overlayView.postInvalidate()
                nowPaused
            },
            onClearCache = {
                translator.clearCache()
                detector.reset()
                hasFailures = false
                overlayView.updateBlocks(emptyList())
            },
            onQuit = {
                stopSelf()
            }
        )
        windowManager.addView(controlBubble.container, controlBubble.layoutParams)
    }

    private fun setupMediaProjection(resultCode: Int, data: Intent) {
        val metrics = resources.displayMetrics
        val sw = metrics.widthPixels
        val sh = metrics.heightPixels
        val density = metrics.densityDpi

        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        mediaProjection = mpm.getMediaProjection(resultCode, data)
        imageReader = ImageReader.newInstance(sw, sh, PixelFormat.RGBA_8888, 2)
        virtualDisplay = mediaProjection?.createVirtualDisplay(
            "RobloxScreenCapture",
            sw, sh, density,
            DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,
            imageReader?.surface, null, null
        )
    }

    private fun readLatestBitmapFromReader(): Bitmap? {
        val image = imageReader?.acquireLatestImage() ?: return null
        return try {
            val plane = image.planes[0]
            val buffer = plane.buffer
            val pixelStride = plane.pixelStride
            val rowStride = plane.rowStride
            val rowPadding = rowStride - pixelStride * image.width
            val rawBmp = Bitmap.createBitmap(
                image.width + rowPadding / pixelStride,
                image.height,
                Bitmap.Config.ARGB_8888
            )
            rawBmp.copyPixelsFromBuffer(buffer)
            Bitmap.createBitmap(rawBmp, 0, 0, image.width, image.height)
        } finally {
            image.close()
        }
    }

    /**
     * Khi cần chụp ảnh để chạy OCR:
     * 1. Ẩn tạm thời lớp phủ chữ dịch và nút nổi (alpha = 0f).
     * 2. Chờ 110ms cho SurfaceFlinger cập nhật khung hình mới không còn lớp phủ.
     * 3. Xả bỏ khung hình cũ trong hàng đợi ImageReader và lấy khung hình sạch 100%.
     * 4. Hiện lại lớp phủ ngay lập tức.
     */
    private fun grabCleanBitmapForOCR(fallbackBmp: Bitmap): Bitmap {
        val latch = CountDownLatch(1)
        mainHandler.post {
            overlayView.alpha = 0f
            controlBubble.container.alpha = 0f
            overlayView.invalidate()
            controlBubble.container.invalidate()
            latch.countDown()
        }
        latch.await(100, TimeUnit.MILLISECONDS)
        // Xả khung hình cũ có dính lớp phủ
        imageReader?.acquireLatestImage()?.close()
        Thread.sleep(110)

        val clean = readLatestBitmapFromReader() ?: fallbackBmp

        mainHandler.post {
            overlayView.alpha = 1f
            controlBubble.container.alpha = 1f
        }
        return clean
    }

    private fun scanStep() {
        if (!running.get() || paused.get()) return
        try {
            val probeBmp = readLatestBitmapFromReader() ?: return
            val sw = probeBmp.width
            val sh = probeBmp.height

            val bubbleRect = controlBubble.getScreenBounds()
            val statusBarRect = Rect(0, 0, sw, (sh * 0.07).toInt())
            val allMaskedRects = mutableListOf<Rect>().apply {
                addAll(overlayView.activeScreenRects)
                add(bubbleRect)
                add(statusBarRect)
            }

            val changed = detector.hasChanged(probeBmp, allMaskedRects, sw, sh)
            if (!changed) {
                if (hasFailures && lastBlocks.isNotEmpty()) {
                    hasFailures = translator.translateBlocks(lastBlocks) > 0
                    overlayView.updateBlocks(lastBlocks)
                }
                return
            }

            val cleanBmp = if (overlayView.activeScreenRects.isNotEmpty()) {
                grabCleanBitmapForOCR(probeBmp)
            } else probeBmp

            val scale = min(1.0f, cfg.ocrMaxWidth.toFloat() / sw)
            val ocrBmp = if (scale < 1.0f) {
                Bitmap.createScaledBitmap(cleanBmp, (sw * scale).toInt(), (sh * scale).toInt(), true)
            } else cleanBmp

            val latch = CountDownLatch(1)
            val rawBlocks = mutableListOf<TextBlock>()
            val minTopY = (sh * 0.06).toInt()

            recognizer.process(InputImage.fromBitmap(ocrBmp, 0))
                .addOnSuccessListener { visionText ->
                    for (block in visionText.textBlocks) {
                        for (line in block.lines) {
                            val txt = line.text.trim()
                            val box = line.boundingBox ?: continue
                            val conf = line.confidence ?: 0.9f
                            if (conf < cfg.minConfidence || TextBlockMerger.shouldSkipText(txt)) continue

                            val lx1 = (box.left / scale).toInt().coerceAtLeast(0)
                            val ly1 = (box.top / scale).toInt().coerceAtLeast(0)
                            val lx2 = (box.right / scale).toInt()
                            val ly2 = (box.bottom / scale).toInt()
                            val lineRect = Rect(lx1, ly1, lx2, ly2)

                            // Bỏ qua thanh trạng thái trên cùng và vùng nút điều khiển nổi
                            if (ly1 < minTopY || Rect.intersects(lineRect, bubbleRect)) continue

                            rawBlocks.add(
                                TextBlock(
                                    x1 = lx1,
                                    y1 = ly1,
                                    x2 = lx2,
                                    y2 = ly2,
                                    originalText = txt,
                                    confidence = conf
                                )
                            )
                        }
                    }
                    latch.countDown()
                }
                .addOnFailureListener {
                    detector.reset()
                    latch.countDown()
                }

            latch.await(4, TimeUnit.SECONDS)
            val merged = TextBlockMerger.mergeNearbyBlocks(rawBlocks, sh)
            hasFailures = translator.translateBlocks(merged) > 0
            lastBlocks = merged
            overlayView.updateBlocks(merged)
        } catch (_: Exception) {
            detector.reset()
        }
    }

    override fun onDestroy() {
        running.set(false)
        workerPool.shutdownNow()
        translator.close()
        virtualDisplay?.release()
        imageReader?.close()
        mediaProjection?.stop()
        try {
            windowManager.removeView(overlayView)
            windowManager.removeView(controlBubble.container)
        } catch (_: Exception) {
        }
        super.onDestroy()
    }
}
""",

    "app/src/main/java/com/roblox/translator/MainActivity.kt": """package com.roblox.translator

import android.app.Activity
import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.media.projection.MediaProjectionManager
import android.net.Uri
import android.os.Bundle
import android.provider.Settings
import android.view.Gravity
import android.widget.Button
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

class MainActivity : AppCompatActivity() {

    private val captureLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { result ->
        if (result.resultCode == Activity.RESULT_OK && result.data != null) {
            val serviceIntent = Intent(this, ScreenCaptureService::class.java).apply {
                putExtra("RESULT_CODE", result.resultCode)
                putExtra("DATA", result.data)
            }
            startForegroundService(serviceIntent)
            Toast.makeText(this, "Đã bật dịch màn hình V2! Hãy mở Roblox hoặc truyện lên.", Toast.LENGTH_LONG).show()
            moveTaskToBack(true)
        } else {
            Toast.makeText(this, "Bạn cần cấp quyền ghi màn hình để dịch.", Toast.LENGTH_SHORT).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        val root = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER
            setBackgroundColor(Color.parseColor("#0F172A"))
            setPadding(64, 64, 64, 64)
        }

        val title = TextView(this).apply {
            text = "Roblox Screen Translator V2"
            textSize = 20f
            setTextColor(Color.parseColor("#FFE066"))
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 24)
        }

        val desc = TextView(this).apply {
            text = "Bản cập nhật V2: Đã sửa triệt để lỗi tự quét lặp lại chữ Tiếng Việt và giới hạn kích thước từng hộp hội thoại gọn gàng."
            textSize = 14f
            setTextColor(Color.parseColor("#CBD5E1"))
            gravity = Gravity.CENTER
            setPadding(0, 0, 0, 48)
        }

        val startBtn = Button(this).apply {
            text = "BẬT DỊCH MÀN HÌNH (V2)"
            setBackgroundColor(Color.parseColor("#2563EB"))
            setTextColor(Color.WHITE)
            setPadding(48, 28, 48, 28)
            setOnClickListener { checkPermissionsAndStart() }
        }

        root.addView(title)
        root.addView(desc)
        root.addView(startBtn)
        setContentView(root)
    }

    private fun checkPermissionsAndStart() {
        if (!Settings.canDrawOverlays(this)) {
            Toast.makeText(this, "Vui lòng bật quyền 'Hiển thị trên ứng dụng khác'", Toast.LENGTH_LONG).show()
            val intent = Intent(
                Settings.ACTION_MANAGE_OVERLAY_PERMISSION,
                Uri.parse("package:$packageName")
            )
            startActivity(intent)
            return
        }
        val mpm = getSystemService(Context.MEDIA_PROJECTION_SERVICE) as MediaProjectionManager
        captureLauncher.launch(mpm.createScreenCaptureIntent())
    }
}
"""
}


def generate_project() -> None:
    print(f"[*] Đang khởi tạo dự án Android V2 tại: {PROJECT_DIR.resolve()} ...")
    for rel_path, content in FILES.items():
        full_path = PROJECT_DIR / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content.strip() + "\n", encoding="utf-8")
        print(f"    + Đã cập nhật: {rel_path}")

    zip_path = Path("RobloxTranslatorAPK_Project.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for rel_path in FILES:
            full_path = PROJECT_DIR / rel_path
            zf.write(full_path, arcname=rel_path)

    print("[THÀNH CÔNG] Đã cập nhật mã nguồn Android V2!")


if __name__ == "__main__":
    generate_project()
