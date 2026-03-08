package me.matheesha.fanbotai.ui.schedule

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.ImageButton
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.fragment.app.viewModels
import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.snackbar.Snackbar
import com.google.android.material.textfield.TextInputEditText
import me.matheesha.fanbotai.R
import me.matheesha.fanbotai.data.local.SettingsRepository
import me.matheesha.fanbotai.data.model.Break
import me.matheesha.fanbotai.data.model.TodaySchedule
import me.matheesha.fanbotai.databinding.FragmentScheduleBinding
import me.matheesha.fanbotai.ui.UiState

class ScheduleFragment : Fragment() {
    private var _binding: FragmentScheduleBinding? = null
    private val binding get() = _binding!!
    private var todayDate = ""

    private val viewModel: ScheduleViewModel by viewModels {
        object : ViewModelProvider.Factory {
            override fun <T : ViewModel> create(modelClass: Class<T>): T {
                @Suppress("UNCHECKED_CAST")
                return ScheduleViewModel(SettingsRepository.getInstance(requireContext())) as T
            }
        }
    }

    override fun onCreateView(inflater: LayoutInflater, container: ViewGroup?, savedInstanceState: Bundle?): View {
        _binding = FragmentScheduleBinding.inflate(inflater, container, false)
        return binding.root
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)
        binding.swipeRefresh.setOnRefreshListener { viewModel.load() }
        binding.fab.setOnClickListener { showAddBreakDialog() }
        viewModel.schedule.observe(viewLifecycleOwner) { state ->
            binding.swipeRefresh.isRefreshing = state is UiState.Loading
            when (state) {
                is UiState.Success -> bindSchedule(state.data)
                is UiState.Error   -> Snackbar.make(view, state.message, Snackbar.LENGTH_LONG).show()
                else -> {}
            }
        }
        viewModel.load()
    }

    private fun bindSchedule(s: TodaySchedule) {
        todayDate = s.date
        binding.tvDate.text        = "Date: ${s.date}"
        binding.tvWindowStart.text = "Window: ${s.windowStart} – ${s.windowEnd}"
        binding.breaksContainer.removeAllViews()
        if (s.breaks.isEmpty()) {
            val tv = TextView(requireContext()).apply { text = "No breaks scheduled"; setPadding(0, 8, 0, 8) }
            binding.breaksContainer.addView(tv)
        } else {
            s.breaks.forEachIndexed { idx, brk -> addBreakRow(brk, idx) }
        }
    }

    private fun addBreakRow(brk: Break, idx: Int) {
        val row = LayoutInflater.from(requireContext()).inflate(R.layout.item_break, binding.breaksContainer, false)
        row.findViewById<TextView>(R.id.tvBreakTime).text = "${brk.start} – ${brk.end}"
        row.findViewById<ImageButton>(R.id.btnDeleteBreak).setOnClickListener {
            MaterialAlertDialogBuilder(requireContext()).setTitle("Delete break")
                .setMessage("Remove break ${brk.start}–${brk.end}?")
                .setPositiveButton("Delete") { _, _ -> viewModel.deleteBreak(todayDate, idx) }
                .setNegativeButton("Cancel", null).show()
        }
        binding.breaksContainer.addView(row)
    }

    private fun showAddBreakDialog() {
        if (todayDate.isEmpty()) return
        val dv = LayoutInflater.from(requireContext()).inflate(R.layout.dialog_break, null)
        val etStart = dv.findViewById<TextInputEditText>(R.id.etBreakStart)
        val etEnd   = dv.findViewById<TextInputEditText>(R.id.etBreakEnd)
        MaterialAlertDialogBuilder(requireContext()).setTitle("Add Break").setView(dv)
            .setPositiveButton("Add") { _, _ ->
                val start = etStart.text.toString().trim()
                val end   = etEnd.text.toString().trim()
                if (start.matches(Regex("\\d{2}:\\d{2}")) && end.matches(Regex("\\d{2}:\\d{2}"))) viewModel.addBreak(todayDate, start, end)
                else Snackbar.make(binding.root, "Use HH:MM format", Snackbar.LENGTH_SHORT).show()
            }.setNegativeButton("Cancel", null).show()
    }

    override fun onDestroyView() { super.onDestroyView(); _binding = null }
}

