package me.matheesha.fanbotai.ui.notes

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.recyclerview.widget.LinearLayoutManager
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.Note
import me.matheesha.fanbotai.databinding.FragmentNotesBinding
import me.matheesha.fanbotai.ui.UiState
import java.time.LocalDate

class NotesFragment : Fragment() {

    private var _binding: FragmentNotesBinding? = null
    private val binding get() = _binding!!

    private val viewModel: NotesViewModel by viewModels {
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return NotesViewModel(SettingsRepository.getInstance(requireContext())) as T
            }
        }
    }

    private lateinit var adapter: NotesAdapter

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentNotesBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        adapter = NotesAdapter(
            onEdit   = { showNoteDialog(it) },
            onDelete = { note ->
                MaterialAlertDialogBuilder(requireContext())
                    .setTitle("Delete note")
                    .setMessage("Delete \"${note.title.ifEmpty { "this note" }}\"?")
                    .setPositiveButton("Delete") { _, _ -> viewModel.deleteNote(note.id) }
                    .setNegativeButton("Cancel", null)
                    .show()
            }
        )
        binding.recyclerView.layoutManager = LinearLayoutManager(requireContext())
        binding.recyclerView.adapter = adapter

        binding.fab.setOnClickListener { showNoteDialog(null) }
        binding.swipeRefresh.setOnRefreshListener { viewModel.load() }

        viewModel.notes.observe(viewLifecycleOwner) { state ->
            binding.swipeRefresh.isRefreshing = state is UiState.Loading
            when (state) {
                is UiState.Success -> {
                    adapter.submitList(state.data)
                    binding.tvEmpty.visibility = if (state.data.isEmpty()) View.VISIBLE else View.GONE
                }
                is UiState.Error -> Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                else -> {}
            }
        }

        viewModel.saveState.observe(viewLifecycleOwner) { state ->
            if (state is UiState.Error) {
                Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                viewModel.resetSaveState()
            }
        }

        viewModel.load()
    }

    private fun showNoteDialog(existing: Note?) {
        val dialogView = LayoutInflater.from(requireContext()).inflate(R.layout.dialog_note, null)
        val etTitle   = dialogView.findViewById<TextInputEditText>(R.id.etNoteTitle)
        val etContent = dialogView.findViewById<TextInputEditText>(R.id.etNoteContent)
        val etDate    = dialogView.findViewById<TextInputEditText>(R.id.etNoteDate)

        existing?.let {
            etTitle.setText(it.title)
            etContent.setText(it.content)
            etDate.setText(it.date)
        } ?: run {
            etDate.setText(LocalDate.now().toString())
        }

        MaterialAlertDialogBuilder(requireContext())
            .setTitle(if (existing == null) "New Note" else "Edit Note")
            .setView(dialogView)
            .setPositiveButton("Save") { _, _ ->
                val date    = etDate.text.toString().trim()
                val title   = etTitle.text.toString().trim()
                val content = etContent.text.toString().trim()
                if (content.isEmpty()) {
                    Snackbar.make(binding.root, "Content is required", Snackbar.LENGTH_SHORT).show()
                    return@setPositiveButton
                }
                if (existing == null) {
                    viewModel.createNote(date, "", title, content)
                } else {
                    viewModel.updateNote(existing.id, date, existing.time, title, content)
                }
            }
            .setNegativeButton("Cancel", null)
            .show()
    }

    override fun onDestroyView() {
        super.onDestroyView()
        _binding = null
    }
}

