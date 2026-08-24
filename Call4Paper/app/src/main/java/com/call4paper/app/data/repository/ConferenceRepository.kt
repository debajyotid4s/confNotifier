package com.call4paper.app.data.repository

import android.util.Log
import com.call4paper.app.data.local.ConferenceDao
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.mappers.toEntities
import com.call4paper.app.data.mappers.toEntity
import com.call4paper.app.data.remote.ApiService
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.withContext
import javax.inject.Inject
import javax.inject.Singleton

private const val TAG = "ConferenceRepo"
private const val DETAIL_TTL_MS = 60 * 60 * 1000L
private const val CALENDAR_FRESHNESS_MS = 15 * 60 * 1000L

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
            val entities = api.getCalendar(month).toEntities()
            dao.insertAll(entities)
            calendarLastFetch[month] = now
            Log.i(TAG, "refreshCalendar: cached ${entities.size} for $month")
        } catch (e: Exception) {
            Log.e(TAG, "refreshCalendar failed for $month", e)
            throw e
        }
    }

    suspend fun refreshUpcoming(limit: Int = 30): List<ConferenceEntity> = withContext(Dispatchers.IO) {
        Log.d(TAG, "refreshUpcoming limit=$limit")
        try {
            val entities = api.getUpcoming(limit).toEntities()
            dao.insertAll(entities)
            entities
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
