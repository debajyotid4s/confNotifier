package com.call4paper.app.ui.calendar

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.ChevronLeft
import androidx.compose.material.icons.filled.ChevronRight
import androidx.compose.material.icons.filled.ErrorOutline
import androidx.compose.material.icons.filled.Inbox
import androidx.compose.material3.*
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.hilt.navigation.compose.hiltViewModel
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import com.call4paper.app.data.local.ConferenceEntity
import com.call4paper.app.data.repository.ConferenceRepository
import com.call4paper.app.ui.theme.urgencyColorFor
import com.call4paper.app.ui.theme.urgencyColorForDate
import dagger.hilt.android.lifecycle.HiltViewModel
import kotlinx.coroutines.flow.*
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.TextStyle
import java.util.Locale
import javax.inject.Inject

private val CardBg = Color(0xFFF2F2F7)
@Composable private fun calendarCardBg() = MaterialTheme.colorScheme.surfaceVariant

data class CalendarUiState(val month: YearMonth = YearMonth.now(), val selected: LocalDate = LocalDate.now(), val items: List<ConferenceEntity> = emptyList(), val loading: Boolean = false, val error: String? = null)

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
            try { repo.refreshCalendar(String.format("%04d-%02d", m.year, m.monthValue)) } catch (_: Exception) { _state.value = _state.value.copy(error = "Could not load calendar — check your connection") }
            _state.value = _state.value.copy(loading = false)
        }
    }
}

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun CalendarScreen(onConference: (Int) -> Unit, vm: CalendarViewModel = hiltViewModel()) {
    val s by vm.state.collectAsState()
    val conferenceDates = remember(s.items) {
        s.items.flatMap { listOfNotNull(it.abstractDeadline, it.fullPaperDeadline) }
            .mapNotNull { runCatching { LocalDate.parse(it) }.getOrNull() }.toSet()
    }
    val listState = rememberLazyListState()
    // Responsive: derivedStateOf prevents recomposition on every pixel; only when progress changes
    val rawProgress by remember {
        derivedStateOf {
            val off = if (listState.firstVisibleItemIndex == 0) listState.firstVisibleItemScrollOffset else 999
            (off / 380f).coerceIn(0f, 1f)
        }
    }
    val eased = androidx.compose.animation.core.FastOutSlowInEasing.transform(rawProgress)
    val calendarAlpha by remember(eased) { derivedStateOf { (1f - eased * 0.85f).coerceIn(0.15f, 1f) } }
    val calendarScale by remember(eased) { derivedStateOf { 1f - eased * 0.02f } }
    val calendarOffset by remember { derivedStateOf { if (listState.firstVisibleItemIndex == 0) -(listState.firstVisibleItemScrollOffset * 0.18f) else -180f } }
    val cardElevation by remember(eased) { derivedStateOf { (8 * (1f - eased * 0.7f)).dp } }

    // All deadlines for this month, sorted
    val allDeadlines = remember(s.items) {
        s.items.flatMap { c ->
            listOfNotNull(
                c.abstractDeadline?.let { Triple(it, c, "Abstract") },
                c.fullPaperDeadline?.let { Triple(it, c, "Full Paper") }
            )
        }.sortedBy { it.first }
    }
    val selStr = s.selected.toString()
    val forDay = allDeadlines.filter { it.first == selStr }

    val themedCardBg = calendarCardBg()
    PullToRefreshBox(
        isRefreshing = s.loading,
        onRefresh = { vm.refresh() },
        modifier = Modifier.fillMaxSize().background(MaterialTheme.colorScheme.background)
    ) {
        LazyColumn(
            state = listState,
            modifier = Modifier.fillMaxSize(),
            contentPadding = PaddingValues(bottom = 16.dp)
        ) {
        // Calendar card — polished collapse: eased alpha + scale + parallax
        item {
            Box(
                Modifier.fillMaxWidth().padding(horizontal = 16.dp).padding(top = 16.dp)
                    .graphicsLayer {
                        alpha = calendarAlpha
                        translationY = calendarOffset
                        scaleX = calendarScale
                        scaleY = calendarScale
                    }
            ) {
                Card(
                    shape = RoundedCornerShape(20.dp),
                    colors = CardDefaults.cardColors(containerColor = themedCardBg),
                    modifier = Modifier.fillMaxWidth().shadow(cardElevation, RoundedCornerShape(20.dp))
                ) {
                    Column(Modifier.padding(16.dp)) {
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                            Text(s.month.month.getDisplayName(TextStyle.FULL, Locale.ENGLISH) + " " + s.month.year, style = MaterialTheme.typography.displaySmall, color = MaterialTheme.colorScheme.onSurface)
                            Row(horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                                Box(Modifier.size(36.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.secondaryContainer).clickable { vm.prev() }, contentAlignment = Alignment.Center) { Icon(Icons.Filled.ChevronLeft, null, tint = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.size(20.dp)) }
                                Box(Modifier.size(36.dp).clip(RoundedCornerShape(8.dp)).background(MaterialTheme.colorScheme.secondaryContainer).clickable { vm.next() }, contentAlignment = Alignment.Center) { Icon(Icons.Filled.ChevronRight, null, tint = MaterialTheme.colorScheme.onSecondaryContainer, modifier = Modifier.size(20.dp)) }
                            }
                        }
                        Spacer(Modifier.height(12.dp)); HorizontalDivider(color = MaterialTheme.colorScheme.outlineVariant, thickness = 1.dp); Spacer(Modifier.height(12.dp))
                        Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            listOf("Mo","Tu","We","Th","Fr","Sa","Su").forEach { Text(it, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurface, modifier = Modifier.weight(1f), textAlign = TextAlign.Center) }
                        }
                        Spacer(Modifier.height(8.dp))
                        val firstDay = s.month.atDay(1)
                        val offset = (firstDay.dayOfWeek.value - DayOfWeek.MONDAY.value + 7) % 7
                        val daysInMonth = s.month.lengthOfMonth()
                        var day = 1
                        for (row in 0..5) {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                                for (col in 0..6) {
                                    val isEmpty = row == 0 && col < offset
                                    val curDay = day
                                    val isInMonth = !isEmpty && curDay <= daysInMonth
                                    val date = if (isInMonth) s.month.atDay(curDay) else null
                                    val isSelected = date != null && date == s.selected
                                    val hasConf = date != null && conferenceDates.contains(date)
                                    val dotColor = if (hasConf && date != null) urgencyColorForDate(date) else Color.Transparent
                                    val selectedBg = if (hasConf) dotColor else MaterialTheme.colorScheme.primary
                                    Box(
                                        Modifier.weight(1f).aspectRatio(1f).padding(2.dp).clip(RoundedCornerShape(8.dp))
                                            .background(if (isSelected) selectedBg else Color.Transparent)
                                            .clickable(enabled = isInMonth) { date?.let { vm.select(it) } },
                                        contentAlignment = Alignment.Center
                                    ) {
                                        if (isInMonth) {
                                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                                Text("$curDay", style = MaterialTheme.typography.bodyMedium, color = when { isSelected -> MaterialTheme.colorScheme.onPrimary; hasConf -> dotColor; else -> MaterialTheme.colorScheme.onSurfaceVariant.copy(alpha = 0.55f) }, fontWeight = if (isSelected) FontWeight.Bold else FontWeight.Normal, textAlign = TextAlign.Center)
                                                if (hasConf && !isSelected) Box(Modifier.size(4.dp).clip(CircleShape).background(dotColor))
                                            }
                                        }
                                    }
                                    if (isInMonth) day++
                                }
                            }
                            if (day > daysInMonth) break
                        }
                    }
                }
            }
        }
        // Month selector
        item {
            Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 12.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                for (m in 1..12) {
                    val isSel = m == s.month.monthValue
                    val monthStr = String.format("%04d-%02d", s.month.year, m)
                    val hasDeadline = s.items.any { it.abstractDeadline?.startsWith(monthStr) == true || it.fullPaperDeadline?.startsWith(monthStr) == true }
                    Column(horizontalAlignment = Alignment.CenterHorizontally, modifier = Modifier.clickable { vm.setMonth(YearMonth.of(s.month.year, m)) }) {
                        Text(YearMonth.of(2021, m).month.getDisplayName(TextStyle.SHORT, Locale.ENGLISH), style = MaterialTheme.typography.labelSmall, color = if (isSel) MaterialTheme.colorScheme.onSurface else MaterialTheme.colorScheme.onSurfaceVariant, fontWeight = if (isSel) FontWeight.Bold else FontWeight.Normal)
                        Spacer(Modifier.height(4.dp))
                        Box(
                            Modifier.size(8.dp)
                                .clip(CircleShape)
                                .background(if (hasDeadline) MaterialTheme.colorScheme.primary else Color.Transparent, CircleShape)
                                .then(if (!hasDeadline) Modifier.border(1.dp, MaterialTheme.colorScheme.outlineVariant, CircleShape) else Modifier)
                        )
                    }
                }
            }
        }
        if (s.loading) item { LinearProgressIndicator(Modifier.fillMaxWidth().padding(horizontal = 16.dp)) }
        s.error?.let { err ->
            item {
                Card(
                    shape = RoundedCornerShape(12.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.errorContainer),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp)
                ) {
                    Column(Modifier.padding(20.dp).fillMaxWidth(), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Icon(Icons.Filled.ErrorOutline, contentDescription = null, tint = MaterialTheme.colorScheme.onErrorContainer, modifier = Modifier.size(32.dp))
                        Text("Couldn't load calendar", style = MaterialTheme.typography.titleSmall, color = MaterialTheme.colorScheme.onErrorContainer)
                        Text(err, style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onErrorContainer)
                        Button(onClick = { vm.refresh() }, shape = RoundedCornerShape(12.dp)) { Text("Retry") }
                    }
                }
            }
        }

        // Selected day agenda — only deadlines on the selected date, not all month
        item {
            Column(Modifier.padding(horizontal = 16.dp)) {
                if (forDay.isNotEmpty()) {
                    Text("Deadlines on ${s.selected} — ${forDay.size} conference(s)", style = MaterialTheme.typography.titleSmall, modifier = Modifier.padding(vertical = 8.dp))
                } else {
                    Text("No submission deadlines on ${s.selected}", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant, modifier = Modifier.padding(vertical = 8.dp))
                }
            }
        }
        if (forDay.isNotEmpty()) {
            items(forDay, key = { it.second.id to it.first }) { (dl, c, label) ->
                val urgency = urgencyColorFor(dl)
                Card(
                    shape = RoundedCornerShape(12.dp),
                    elevation = CardDefaults.cardElevation(defaultElevation = 2.dp),
                    colors = CardDefaults.cardColors(containerColor = MaterialTheme.colorScheme.surface),
                    modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 4.dp).clickable { onConference(c.id) }
                ) {
                    Row(Modifier.fillMaxWidth().height(IntrinsicSize.Min)) {
                        Box(Modifier.width(3.dp).fillMaxHeight().background(urgency))
                        Column(Modifier.padding(14.dp).weight(1f), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                            Text(c.title, style = MaterialTheme.typography.titleMedium, maxLines = 2)
                            Text("$label: $dl", style = MaterialTheme.typography.labelMedium, color = urgency)
                            Text(listOfNotNull(c.city, c.organizer).joinToString(" · ").ifEmpty { c.website ?: "" }, style = MaterialTheme.typography.labelSmall, color = MaterialTheme.colorScheme.onSurfaceVariant, maxLines = 1)
                        }
                    }
                }
            }
        } else {
            item {
                Box(Modifier.fillMaxWidth().padding(16.dp), contentAlignment = Alignment.Center) {
                    Text("Tap a red-dotted date to see its deadlines", style = MaterialTheme.typography.bodySmall, color = MaterialTheme.colorScheme.onSurfaceVariant)
                }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
        }
    }
}
