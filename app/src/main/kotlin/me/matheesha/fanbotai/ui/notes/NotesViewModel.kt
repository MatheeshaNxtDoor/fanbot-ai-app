package me.matheesha.fanbotai.ui.notes

import androidx.lifecycle.LiveData
import androidx.lifecycle.MutableLiveData
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.launch
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.Note
import me.matheesha.fanbotai.data.repository.NotesRepository
import me.matheesha.fanbotai.data.repository.Result
import me.matheesha.fanbotai.ui.UiState

class NotesViewModel(settings: SettingsRepository) : ViewModel() {
    private val repo = NotesRepository(settings)

    private val _notes = MutableLiveData<UiState<List<Note>>>(UiState.Idle)
    val notes: LiveData<UiState<List<Note>>> = _notes

    private val _saveState = MutableLiveData<UiState<Note>>(UiState.Idle)
    val saveState: LiveData<UiState<Note>> = _saveState

    fun load() {
        _notes.value = UiState.Loading
        viewModelScope.launch {
            _notes.value = when (val r = repo.getNotes()) {
                is Result.Success -> UiState.Success(r.data)
                is Result.Error   -> UiState.Error(r.message)
            }
        }
    }

    fun createNote(date: String, time: String, title: String, content: String) {
        _saveState.value = UiState.Loading
        viewModelScope.launch {
            when (val r = repo.createNote(date, time, title, content)) {
                is Result.Success -> { _saveState.value = if (r.data.ok && r.data.note != null) UiState.Success(r.data.note) else UiState.Error("Failed"); load() }
                is Result.Error   -> _saveState.value = UiState.Error(r.message)
            }
        }
    }

    fun updateNote(id: String, date: String, time: String, title: String, content: String) {
        _saveState.value = UiState.Loading
        viewModelScope.launch {
            when (val r = repo.updateNote(id, date, time, title, content)) {
                is Result.Success -> { _saveState.value = if (r.data.ok && r.data.note != null) UiState.Success(r.data.note) else UiState.Error("Failed"); load() }
                is Result.Error   -> _saveState.value = UiState.Error(r.message)
            }
        }
    }

    fun deleteNote(id: String) { viewModelScope.launch { repo.deleteNote(id); load() } }
    fun resetSaveState() { _saveState.value = UiState.Idle }
}

