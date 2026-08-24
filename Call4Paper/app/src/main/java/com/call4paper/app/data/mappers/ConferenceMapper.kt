package com.call4paper.app.data.mappers

import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.remote.ConferenceDto

fun ConferenceDto.toEntity() = ConferenceEntity(
    id = id,
    title = name,
    website = website,
    startDate = start_date,
    endDate = end_date,
    city = location,
    organizer = organizer,
    category = category,
    abstractDeadline = abstract_deadline,
    fullPaperDeadline = full_paper_deadline,
    description = description
)

fun List<ConferenceDto>.toEntities(): List<ConferenceEntity> = map { it.toEntity() }
