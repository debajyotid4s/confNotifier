package com.call4paper.app.data.local

import androidx.room.Database
import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import kotlinx.coroutines.flow.Flow

@Dao
interface ConferenceDao {
    @Query("SELECT * FROM conferences ORDER BY startDate ASC")
    fun observeAll(): Flow<List<ConferenceEntity>>

    @Query("SELECT * FROM conferences WHERE id = :id")
    suspend fun getById(id: Int): ConferenceEntity?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insertAll(items: List<ConferenceEntity>)

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun insert(item: ConferenceEntity)

    @Query("DELETE FROM conferences WHERE updatedAt < :cutoff")
    suspend fun pruneOlderThan(cutoff: Long)

    @Query("DELETE FROM conferences")
    suspend fun clear()
}

@Database(entities = [ConferenceEntity::class], version = 2, exportSchema = false)
abstract class AppDatabase : androidx.room.RoomDatabase() {
    abstract fun conferenceDao(): ConferenceDao
}
