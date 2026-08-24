package com.call4paper.app.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import com.call4paper.app.data.UrgencyLevel
import com.call4paper.app.data.daysUntil
import com.call4paper.app.data.isTba
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.soonestDeadline
import com.call4paper.app.data.urgencyLevel
import java.time.LocalDate

val WarningAmber = Color(0xFFF9A825)
val TbaGray = Color(0xFF9E9E9E)

@Composable
fun urgencyColor(level: UrgencyLevel): Color = when (level) {
    UrgencyLevel.PAST -> MaterialTheme.colorScheme.outlineVariant
    UrgencyLevel.CRITICAL -> MaterialTheme.colorScheme.error
    UrgencyLevel.WARNING -> WarningAmber
    UrgencyLevel.NORMAL -> MaterialTheme.colorScheme.outlineVariant
    UrgencyLevel.TBA -> MaterialTheme.colorScheme.outlineVariant
}

@Composable
fun urgencyColorForDeadline(deadlineStr: String?, today: LocalDate = LocalDate.now()): Color =
    urgencyColor(urgencyLevel(deadlineStr, today))

@Composable
fun urgencyColorFor(deadlineStr: String, today: LocalDate = LocalDate.now()): Color =
    urgencyColorForDeadline(deadlineStr, today)

@Composable
fun urgencyColorForDate(date: LocalDate, today: LocalDate = LocalDate.now()): Color {
    val days = daysUntil(date.toString(), today) ?: return MaterialTheme.colorScheme.outlineVariant
    return when {
        days < 0 -> MaterialTheme.colorScheme.outlineVariant
        days < 3 -> MaterialTheme.colorScheme.error
        days <= 14 -> WarningAmber
        else -> MaterialTheme.colorScheme.outlineVariant
    }
}

@Composable
fun urgencyForEntity(entity: ConferenceEntity): Color {
    if (entity.isTba()) return TbaGray
    return urgencyColorForDeadline(entity.soonestDeadline())
}
