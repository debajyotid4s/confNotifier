package com.call4paper.app.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

// Seed #1A2B4C — academic ink/navy. Red is wired as error/urgent, not a floating hex.
private val LightColors = lightColorScheme(
    primary = Color(0xFF1A2B4C),
    onPrimary = Color(0xFFFFFFFF),
    primaryContainer = Color(0xFFD9E3FF),
    onPrimaryContainer = Color(0xFF001A3E),
    secondary = Color(0xFF535F70),
    onSecondary = Color(0xFFFFFFFF),
    secondaryContainer = Color(0xFFE2EAF9),
    onSecondaryContainer = Color(0xFF121C2B),
    tertiary = Color(0xFF6B5778),
    onTertiary = Color(0xFFFFFFFF),
    tertiaryContainer = Color(0xFFF2DAFF),
    onTertiaryContainer = Color(0xFF251544),
    background = Color(0xFFF8F9FF),
    onBackground = Color(0xFF1A1C1E),
    surface = Color(0xFFF8F9FF),
    onSurface = Color(0xFF1A1C1E),
    surfaceVariant = Color(0xFFE1E2EC),
    onSurfaceVariant = Color(0xFF44474E),
    outline = Color(0xFF74777F),
    outlineVariant = Color(0xFFC4C6D0),
    error = Color(0xFFE53935),
    onError = Color(0xFFFFFFFF),
    errorContainer = Color(0xFFFFDAD6),
    onErrorContainer = Color(0xFF410002)
)

private val DarkColors = darkColorScheme(
    primary = Color(0xFFAAC7FF),
    onPrimary = Color(0xFF0A305F),
    primaryContainer = Color(0xFF284777),
    onPrimaryContainer = Color(0xFFD9E3FF),
    secondary = Color(0xFFBCC7DB),
    onSecondary = Color(0xFF253141),
    secondaryContainer = Color(0xFF3E4758),
    onSecondaryContainer = Color(0xFFE2EAF9),
    tertiary = Color(0xFFD9B9E5),
    onTertiary = Color(0xFF3F2A4A),
    tertiaryContainer = Color(0xFF564163),
    onTertiaryContainer = Color(0xFFF2DAFF),
    background = Color(0xFF121315),
    onBackground = Color(0xFFE2E2E6),
    surface = Color(0xFF121315),
    onSurface = Color(0xFFE2E2E6),
    surfaceVariant = Color(0xFF44474E),
    onSurfaceVariant = Color(0xFFC4C6D0),
    outline = Color(0xFF8E9199),
    outlineVariant = Color(0xFF44474E),
    error = Color(0xFFFFB4AB),
    onError = Color(0xFF690005),
    errorContainer = Color(0xFF93000A),
    onErrorContainer = Color(0xFFFFDAD6)
)

@Composable
fun Call4PaperTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = if (darkTheme) DarkColors else LightColors,
        typography = AppTypography,
        content = content
    )
}
