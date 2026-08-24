package com.call4paper.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.call4paper.app.data.local.ConferenceEntity
import java.time.LocalDate
import java.time.temporal.ChronoUnit

val WarningAmber = Color(0xFFF9A825)
val TbaGray = Color(0xFF9E9E9E)

fun isTbaEntity(entity: ConferenceEntity): Boolean {
    return entity.abstractDeadline == null && entity.fullPaperDeadline == null && entity.startDate == null
}

@Composable
fun urgencyColorForDeadline(deadlineStr: String?, today: LocalDate = LocalDate.now()): Color {
    val d = deadlineStr?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: return MaterialTheme.colorScheme.outlineVariant
    val days = ChronoUnit.DAYS.between(today, d)
    return when {
        days < 0 -> MaterialTheme.colorScheme.outlineVariant
        days < 3 -> MaterialTheme.colorScheme.error
        days <= 14 -> WarningAmber
        else -> MaterialTheme.colorScheme.outlineVariant
    }
}

@Composable
fun urgencyColorFor(deadlineStr: String, today: LocalDate = LocalDate.now()): Color = urgencyColorForDeadline(deadlineStr, today)

@Composable
fun urgencyColorForDate(date: LocalDate, today: LocalDate = LocalDate.now()): Color {
    val days = ChronoUnit.DAYS.between(today, date)
    return when {
        days < 0 -> MaterialTheme.colorScheme.outlineVariant
        days < 3 -> MaterialTheme.colorScheme.error
        days <= 14 -> WarningAmber
        else -> MaterialTheme.colorScheme.outlineVariant
    }
}

@Composable
fun urgencyForEntity(entity: ConferenceEntity): Color {
    if (isTbaEntity(entity)) return TbaGray
    return urgencyColorForDeadline(entity.abstractDeadline ?: entity.fullPaperDeadline ?: entity.startDate)
}
