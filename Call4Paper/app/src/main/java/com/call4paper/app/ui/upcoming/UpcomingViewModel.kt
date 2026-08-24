package com.call4paper.app.ui.upcoming

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.repository.ConferenceRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltViewModel
class UpcomingViewModel @Inject constructor(private val repo: ConferenceRepository) : ViewModel() {
    private val _state = MutableStateFlow<List<ConferenceEntity>>(emptyList())
    val state: StateFlow<List<ConferenceEntity>> = _state.asStateFlow()
    private val _error = MutableStateFlow<String?>(null)
    val error: StateFlow<String?> = _error.asStateFlow()
    private val _isRefreshing = MutableStateFlow(false)
    val isRefreshing: StateFlow<Boolean> = _isRefreshing.asStateFlow()
    init { refresh() }
    fun refresh() {
        viewModelScope.launch {
            _isRefreshing.value = true
            _error.value = null
            try { _state.value = repo.refreshUpcoming(50) }
            catch (e: CancellationException) { throw e }
            catch (_: Exception) { _error.value = "Could not load — check your connection" }
            _isRefreshing.value = false
        }
    }
}
