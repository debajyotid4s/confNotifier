package com.call4paper.app.data

import com.call4paper.app.data.local.ConferenceEntity
import java.time.LocalDate
import java.time.temporal.ChronoUnit

enum class UrgencyLevel { PAST, CRITICAL, WARNING, NORMAL, TBA }

fun ConferenceEntity.soonestDeadline(): String? = abstractDeadline ?: fullPaperDeadline ?: startDate

fun ConferenceEntity.isTba(): Boolean =
    abstractDeadline == null && fullPaperDeadline == null && startDate == null

fun deadlineLabel(abstract: String?, fullPaper: String?): String? = when {
    abstract != null -> "Abstract"
    fullPaper != null -> "Full paper"
    else -> null
}

fun deadlineLabelLong(abstract: String?, fullPaper: String?, startDate: String?): String = when {
    abstract != null -> "Abstract submission"
    fullPaper != null -> "Full paper submission"
    else -> "Starts"
}

fun daysUntil(dateStr: String?, today: LocalDate = LocalDate.now()): Long? {
    if (dateStr == null) return null
    val d = runCatching { LocalDate.parse(dateStr) }.getOrNull() ?: return null
    return ChronoUnit.DAYS.between(today, d)
}

fun urgencyLevel(dateStr: String?, today: LocalDate = LocalDate.now()): UrgencyLevel {
    val days = daysUntil(dateStr, today) ?: return UrgencyLevel.TBA
    return when {
        days < 0 -> UrgencyLevel.PAST
        days < 3 -> UrgencyLevel.CRITICAL
        days <= 14 -> UrgencyLevel.WARNING
        else -> UrgencyLevel.NORMAL
    }
}

fun ConferenceEntity.deadlineDisplayLong(today: LocalDate = LocalDate.now()): String {
    if (isTba()) return "To be announced"
    val label = deadlineLabelLong(abstractDeadline, fullPaperDeadline, startDate)
    val dateStr = soonestDeadline() ?: return ""
    return "$label: $dateStr"
}
