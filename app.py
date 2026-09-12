    # Chat input
    user_msg = st.chat_input("Type your order...")
    if user_msg:
        st.session_state.messages.append({"role": "user", "content": user_msg})
        with st.chat_message("user"):
            st.markdown(user_msg)

        with st.chat_message("assistant"):
            with st.spinner("Ek second..."):
                parsed = classify_message(user_msg)
                intent = parsed.get("intent", "other")
                language = parsed.get("language", "en")
                products = parsed.get("products", [])
                mismatches = parsed.get("unit_mismatch", [])

                # ---- Priority 1: unit mismatch — ask for clarification ----
                if mismatches:
                    m = mismatches[0]
                    real = find_product(m.get("product", ""))
                    data = {
                        "mismatch": {
                            "product": m.get("product"),
                            "customer_said_unit": m.get("customer_said_unit"),
                            "catalog_unit": real["unit"] if real else "?",
                            "price_per_unit": float(real["unit_price"]) if real else 0,
                            "stock": float(real["current_stock"]) if real else 0,
                        }
                    }
                    reply = generate_reply(user_msg, "unit_mismatch", data, language)

                # ---- Priority 2: quantity exceeds stock ----
                elif any(p.get("exceeds_stock") for p in products):
                    bad = next(p for p in products if p.get("exceeds_stock"))
                    data = {
                        "mismatch": {
                            "product": bad["product"],
                            "unit": bad["unit"],
                            "requested": bad["quantity"],
                            "stock": bad["stock_available"],
                        }
                    }
                    reply = generate_reply(user_msg, "stock_exceeded", data, language)

                # ---- Greeting ----
                elif intent == "greeting":
                    reply = generate_reply(user_msg, intent, {"note": "customer greeted"}, language)

                # ---- Inventory query ----
                elif intent == "inventory_query":
                    all_items = cached_full_inventory()
                    in_stock = [it for it in all_items if it["stock"] > 0]
                    data = {
                        "query_type": "full_inventory",
                        "all_items": in_stock,
                        "total_products": len(all_items),
                        "in_stock_count": len(in_stock),
                    }
                    reply = generate_reply(user_msg, intent, data, language)

                # ---- Product availability ----
                elif intent == "product_query":
                    if products:
                        p = products[0]
                        real = get_product_by_id(p["product_id"])
                        data = {
                            "product": {
                                "name": real["name"],
                                "unit": real["unit"],
                                "unit_price": float(real["unit_price"]),
                                "stock": float(real["current_stock"]),
                            }
                        }
                        reply = generate_reply(user_msg, intent, data, language)
                    else:
                        all_items = cached_full_inventory()
                        in_stock = [it for it in all_items if it["stock"] > 0]
                        reply = generate_reply(user_msg, "inventory_query",
                                               {"all_items": in_stock}, language)

                # ---- Price query ----
                elif intent == "price_query":
                    if products:
                        p = products[0]
                        real = get_product_by_id(p["product_id"])
                        data = {
                            "product": {
                                "name": real["name"],
                                "unit": real["unit"],
                                "unit_price": float(real["unit_price"]),
                                "stock": float(real["current_stock"]),
                            }
                        }
                        reply = generate_reply(user_msg, intent, data, language)
                    else:
                        all_items = cached_full_inventory()
                        reply = generate_reply(user_msg, "inventory_query",
                                               {"all_items": all_items}, language)

                # ---- Order intent ----
                elif intent == "order_intent":
                    if products:
                        _add_to_draft(products)
                        draft = st.session_state.draft_items
                        items_for_reply = [
                            {"name": d["product"], "qty": d["quantity"], "unit": d["unit"]}
                            for d in draft
                        ]
                        total = sum(d["quantity"] * d["unit_price"] for d in draft)
                        data = {
                            "added_items": [
                                {"name": p["product"], "qty": p["quantity"], "unit": p["unit"]}
                                for p in products
                            ],
                            "current_draft": items_for_reply,
                            "draft_total": total,
                        }
                        reply = generate_reply(user_msg, intent, data, language)
                    else:
                        all_items = cached_full_inventory()
                        in_stock = [it for it in all_items if it["stock"] > 0]
                        reply = generate_reply(user_msg, "inventory_query",
                                               {"all_items": in_stock}, language)

                # ---- Confirm / Cancel ----
                elif intent == "confirm":
                    reply = "Confirm karne ke liye neeche 'Confirm Order' button dabaiye. 🙂"
                elif intent == "cancel":
                    st.session_state.draft_items = []
                    reply = generate_reply(user_msg, intent, {"note": "order cancelled"}, language)

                # ---- Fallback ----
                else:
                    all_items = cached_full_inventory()
                    in_stock = [it for it in all_items if it["stock"] > 0]
                    reply = generate_reply(user_msg, "inventory_query",
                                           {"all_items": in_stock}, language)

                st.markdown(reply)
                st.session_state.messages.append({"role": "assistant", "content": reply})
                _trim_messages()
                st.rerun()
