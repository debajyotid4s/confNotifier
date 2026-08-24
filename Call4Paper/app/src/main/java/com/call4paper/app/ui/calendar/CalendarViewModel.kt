package com.call4paper.app.ui.calendar

import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.repository.ConferenceRepository
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.YearMonth
import javax.inject.Inject

data class CalendarUiState(
    val month: YearMonth = YearMonth.now(),
    val selected: LocalDate = LocalDate.now(),
    val items: List<ConferenceEntity> = emptyList(),
    val loading: Boolean = false,
    val error: String? = null
)

@HiltViewModel
class CalendarViewModel @Inject constructor(private val repo: ConferenceRepository) : ViewModel() {
    private val _month = MutableStateFlow(YearMonth.now())
    private val _selected = MutableStateFlow(LocalDate.now())
    private val _state = MutableStateFlow(CalendarUiState())
    val state: StateFlow<CalendarUiState> = _state.asStateFlow()
    init {
        viewModelScope.launch {
            combine(_month, _selected, repo.observeAll()) { m, sel, list ->
                val monthStr = String.format("%04d-%02d", m.year, m.monthValue)
                CalendarUiState(month = m, selected = sel, items = list.filter {
                    it.abstractDeadline?.startsWith(monthStr) == true || it.fullPaperDeadline?.startsWith(monthStr) == true
                })
            }.collect { _state.value = it }
        }
        viewModelScope.launch { _month.collect { refresh(it) } }
    }
    fun setMonth(m: YearMonth) { _month.value = m }
    fun select(date: LocalDate) { _selected.value = date }
    fun prev() { _month.value = _month.value.minusMonths(1) }
    fun next() { _month.value = _month.value.plusMonths(1) }
    fun refresh(m: YearMonth = _month.value) {
        viewModelScope.launch {
            _state.value = _state.value.copy(loading = true)
            try { repo.refreshCalendar(String.format("%04d-%02d", m.year, m.monthValue)) } catch (e: CancellationException) { throw e } catch (_: Exception) { _state.value = _state.value.copy(error = "Could not load calendar — check your connection") }
            _state.value = _state.value.copy(loading = false)
        }
    }
}
