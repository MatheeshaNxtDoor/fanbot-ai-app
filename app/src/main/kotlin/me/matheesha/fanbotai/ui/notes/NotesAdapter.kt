package me.matheesha.fanbotai.ui.notes

import android.view.LayoutInflater
import android.view.ViewGroup
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import me.matheesha.fanbotai.data.model.Note
import me.matheesha.fanbotai.databinding.ItemNoteBinding

class NotesAdapter(
    private val onEdit: (Note) -> Unit,
    private val onDelete: (Note) -> Unit
) : ListAdapter<Note, NotesAdapter.ViewHolder>(DIFF) {

    inner class ViewHolder(private val b: ItemNoteBinding) : RecyclerView.ViewHolder(b.root) {
        fun bind(note: Note) {
            b.tvTitle.text   = note.title.ifEmpty { "Untitled" }
            b.tvContent.text = note.content
            b.tvDate.text    = "${note.date} ${note.time}".trim()
            b.btnEdit.setOnClickListener   { onEdit(note) }
            b.btnDelete.setOnClickListener { onDelete(note) }
        }
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int) = ViewHolder(
        ItemNoteBinding.inflate(LayoutInflater.from(parent.context), parent, false)
    )
    override fun onBindViewHolder(holder: ViewHolder, position: Int) = holder.bind(getItem(position))

    companion object {
        val DIFF = object : DiffUtil.ItemCallback<Note>() {
            override fun areItemsTheSame(oldItem: Note, newItem: Note) = oldItem.id == newItem.id
            override fun areContentsTheSame(oldItem: Note, newItem: Note) = oldItem == newItem
        }
    }
}

