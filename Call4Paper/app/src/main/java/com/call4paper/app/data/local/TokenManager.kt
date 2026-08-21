package com.call4paper.app.data.local

import android.content.Context
import androidx.datastore.preferences.core.edit
import androidx.datastore.preferences.core.stringPreferencesKey
import androidx.datastore.preferences.preferencesDataStore
import dagger.hilt.android.qualifiers.ApplicationContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import javax.inject.Inject
import javax.inject.Singleton

private val Context.authStore by preferencesDataStore(name = "auth_prefs")

@Singleton
class TokenManager @Inject constructor(@ApplicationContext private val ctx: Context) {
    private val KEY = stringPreferencesKey("app_token")
    val tokenFlow: Flow<String?> = ctx.authStore.data.map { it[KEY] }
    suspend fun save(token: String) { ctx.authStore.edit { it[KEY] = token } }
    suspend fun clear() { ctx.authStore.edit { it.remove(KEY) } }
    suspend fun peek(): String? = ctx.authStore.data.first()[KEY]
}
