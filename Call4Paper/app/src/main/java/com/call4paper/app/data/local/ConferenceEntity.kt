package com.call4paper.app.data.local

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "conferences")
data class ConferenceEntity(
    @PrimaryKey val id: Int,
    val title: String,
    val website: String?,
    val startDate: String?,
    val endDate: String?,
    val city: String?,
    val organizer: String?,
    val category: String?,
    val abstractDeadline: String? = null,
    val fullPaperDeadline: String? = null,
    val updatedAt: Long = System.currentTimeMillis()
)
