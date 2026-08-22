package com.call4paper.app.data.repository

import android.util.Log
import com.call4paper.app.data.local.ConferenceDao
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.remote.ApiService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "ConferenceRepo"
private const val DETAIL_TTL_MS = 60 * 60 * 1000L // 1h
private const val CALENDAR_FRESHNESS_MS = 15 * 60 * 1000L // 15min per month
private const val PRUNE_AFTER_MS = 7 * 24 * 60 * 60 * 1000L // keep 7d of past data

@Singleton
class ConferenceRepository @Inject constructor(
    private val api: ApiService,
    private val dao: ConferenceDao
) {
    private val calendarLastFetch = mutableMapOf<String, Long>()

    fun observeAll(): Flow<List<ConferenceEntity>> = dao.observeAll()

    suspend fun refreshCalendar(month: String, force: Boolean = false) = withContext(Dispatchers.IO) {
        val now = System.currentTimeMillis()
        val last = calendarLastFetch[month] ?: 0L
        if (!force && now - last < CALENDAR_FRESHNESS_MS) {
            Log.d(TAG, "refreshCalendar: skipping $month (fresh ${ (now-last)/1000 }s ago)")
            return@withContext
        }
        Log.d(TAG, "refreshCalendar: $month")
        try {
            val dtos = api.getCalendar(month)
            val entities = dtos.map { it.toEntity() }
            dao.insertAll(entities)
            calendarLastFetch[month] = now
            Log.i(TAG, "refreshCalendar: cached ${entities.size} for $month")
        } catch (e: Exception) {
            Log.e(TAG, "refreshCalendar failed for $month", e)
            throw e
        }
    }

    suspend fun refreshUpcoming(limit: Int = 30) = withContext(Dispatchers.IO) {
        Log.d(TAG, "refreshUpcoming limit=$limit")
        try {
            val dtos = api.getUpcoming(limit)
            dao.insertAll(dtos.map { it.toEntity() })
        } catch (e: Exception) {
            Log.e(TAG, "refreshUpcoming failed", e); throw e
        }
    }

    suspend fun getDetail(id: Int): ConferenceEntity? = withContext(Dispatchers.IO) {
        val cached = dao.getById(id)
        if (cached != null && System.currentTimeMillis() - cached.updatedAt < DETAIL_TTL_MS) {
            return@withContext cached
        }
        // Fetch from network (force refresh if stale or missing)
        try {
            val dto = api.getConference(id)
            val entity = dto.toEntity()
            dao.insert(entity); entity
        } catch (e: Exception) {
            // On network failure, return stale cache if exists
            if (cached != null) return@withContext cached
            Log.e(TAG, "getDetail $id failed", e); null
        }
    }
}

private fun com.call4paper.app.data.remote.ConferenceDto.toEntity() = ConferenceEntity(
    id = id,
    title = name,
    website = website,
    startDate = start_date,
    endDate = end_date,
    city = location,
    organizer = organizer,
    category = category,
    abstractDeadline = abstract_deadline,
    fullPaperDeadline = full_paper_deadline
)
