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

@Singleton
class ConferenceRepository @Inject constructor(
    private val api: ApiService,
    private val dao: ConferenceDao
) {
    fun observeAll(): Flow<List<ConferenceEntity>> = dao.observeAll()

    suspend fun refreshCalendar(month: String) = withContext(Dispatchers.IO) {
        Log.d(TAG, "refreshCalendar: $month")
        try {
            val dtos = api.getCalendar(month)
            val entities = dtos.map { it.toEntity() }
            dao.insertAll(entities)
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
        // Try cache first
        dao.getById(id)?.let { return@withContext it }
        // Fetch from network
        try {
            val dto = api.getConference(id)
            val entity = dto.toEntity()
            dao.insert(entity); entity
        } catch (e: Exception) { Log.e(TAG, "getDetail $id failed", e); null }
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
