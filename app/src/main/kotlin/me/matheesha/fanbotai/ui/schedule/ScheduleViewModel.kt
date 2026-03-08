package me.matheesha.fanbotai.ui.schedule

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.TodaySchedule
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.data.repository.ScheduleRepository
import me.matheesha.fanbotai.ui.UiState

class ScheduleViewModel(settings: SettingsRepository) : ViewModel() {
    private val repo = ScheduleRepository(settings)

    private val _schedule = MutableLiveData<UiState<TodaySchedule>>(UiState.Idle)
    val schedule: LiveData<UiState<TodaySchedule>> = _schedule

    fun load() {
        _schedule.value = UiState.Loading
        viewModelScope.launch {
            _schedule.value = when (val r = repo.getTodaySchedule()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }

    fun addBreak(date: String, start: String, end: String) { viewModelScope.launch { repo.addBreak(date, start, end); load() } }
    fun deleteBreak(date: String, idx: Int) { viewModelScope.launch { repo.deleteBreak(date, idx); load() } }
}

